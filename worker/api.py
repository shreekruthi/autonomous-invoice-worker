import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from worker.company import FaultRequest, create_company, require_latest, token_check
from worker.config import Settings
from worker.domain import InvoiceError, Review, TaskRequest, digest, parse_invoice
from worker.engine import Engine
from worker.groq_planner import GroqPlanner
from worker.planner import DemoPlanner, OpenAIPlanner
from worker.store import Store, now


def create_app(settings: Settings | None = None, planner=None):
    settings = settings or Settings.from_env()
    settings.make_parent()
    store = Store(settings.db_path)
    company = create_company(store, settings)
    if planner is None:
        planner = {
            "demo": DemoPlanner,
            "openai": lambda: OpenAIPlanner(settings),
            "groq": lambda: GroqPlanner(
                settings, on_wait=lambda task, info: store.event(task["id"], "provider_wait", info)
            ),
        }[settings.mode]()
    engine = Engine(store, settings, company, planner)

    @asynccontextmanager
    async def lifespan(app):
        store.seed()
        store.recover()
        yield

    app = FastAPI(title="CentrAlign Invoice Worker", version="0.1.0", lifespan=lifespan)
    app.state.store, app.state.engine, app.state.settings = store, engine, settings
    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")
    app.mount("/company", company)
    worker_auth = Depends(token_check(settings.worker_token))
    reviewer_auth = Depends(token_check(settings.reviewer_token))

    def get_task(task_id):
        try:
            return store.task(task_id)
        except KeyError:
            raise HTTPException(404, "Task not found") from None

    @app.get("/")
    def index():
        return FileResponse(static / "index.html")

    @app.get("/health")
    def health():
        return {"status": "ok", "mode": settings.mode, "version": "0.1.0"}

    @app.get("/api/config", dependencies=[worker_auth])
    def config():
        return {
            "mode": settings.mode,
            "model": {"openai": settings.model, "groq": settings.groq_model}.get(settings.mode),
            "approval_threshold_minor": settings.approval_threshold_minor,
            "max_steps": settings.max_steps,
            "faults_enabled": settings.enable_faults,
        }

    @app.get("/api/tasks", dependencies=[worker_auth])
    def tasks():
        return [{k: v for k, v in row.items() if k != "memory"} for row in reversed(store.rows("tasks"))]

    @app.post("/api/tasks", dependencies=[worker_auth], status_code=201)
    async def create_task(body: TaskRequest):
        task = store.create_task(body.goal, settings.mode)
        return await engine.run(task["id"])

    @app.get("/api/tasks/{task_id}", dependencies=[worker_auth])
    def task(task_id: str):
        return get_task(task_id)

    @app.get("/api/tasks/{task_id}/events", dependencies=[worker_auth])
    def events(task_id: str):
        get_task(task_id)
        return store.events(task_id)

    @app.get("/api/tasks/{task_id}/export", dependencies=[worker_auth])
    def export(task_id: str):
        bundle = {"task": get_task(task_id), "events": store.events(task_id)}
        return Response(
            json.dumps(bundle, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="task-{task_id}.json"'},
        )

    @app.post("/api/tasks/{task_id}/review", dependencies=[reviewer_auth])
    async def review(task_id: str, body: Review):
        async with engine.lock:
            task = get_task(task_id)
            if task["status"] != "awaiting_approval":
                raise HTTPException(409, "Only a task awaiting approval can be reviewed")
            expected = task["memory"]["prepared"]
            try:
                actual = parse_invoice(store.source(expected["source_id"]))
                require_latest(store, expected["vendor_id"], expected["source_id"])
                if actual != expected:
                    raise InvoiceError(
                        "Source changed; approval is stale. Clarify/restart to review current fields."
                    )
            except (InvoiceError, KeyError) as exc:
                raise HTTPException(409, str(exc)) from exc
            fingerprint = digest(expected)
            task["memory"]["approved"] = body.decision == "approve"
            if "llm_history" in task["memory"]:
                task["memory"]["llm_history"].append(
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "runtime_event": "human_review",
                                "decision": body.decision,
                                "fingerprint": fingerprint,
                            }
                        ),
                    }
                )
            task["status"] = "pending" if body.decision == "approve" else "rejected"
            task["summary"] = (
                "Approved for recording" if body.decision == "approve" else "Human reviewer rejected invoice"
            )
            with store.connect() as db:
                changed = db.execute(
                    "UPDATE approvals SET decision=?,reviewer=?,note=?,updated_at=? "
                    "WHERE task_id=? AND fingerprint=? AND decision='pending'",
                    (body.decision, body.reviewer, body.note, now(), task_id, fingerprint),
                ).rowcount
                if not changed:
                    raise HTTPException(409, "Approval has already been decided or is missing")
                db.execute(
                    "UPDATE tasks SET status=?,memory=?,summary=?,updated_at=? WHERE id=?",
                    (task["status"], json.dumps(task["memory"]), task["summary"], now(), task_id),
                )
            store.event(task_id, "human_review", body.model_dump() | {"fingerprint": fingerprint})
        return await engine.run(task_id) if body.decision == "approve" else store.task(task_id)

    @app.post("/api/tasks/{task_id}/clarify", dependencies=[worker_auth])
    async def clarify(task_id: str, body: TaskRequest):
        async with engine.lock:
            task = get_task(task_id)
            if task["status"] not in {"needs_input", "awaiting_approval", "failed", "interrupted"}:
                raise HTTPException(409, "Task cannot be clarified in its current state")
            # Invalidate old approvals. Keep their rows and the event history for audit.
            with store.connect() as db:
                db.execute(
                    "UPDATE approvals SET decision='superseded' WHERE task_id=? "
                    "AND decision IN ('pending','approve')",
                    (task_id,),
                )
            task.update(goal=body.goal, status="pending", memory={}, summary="", steps=0)
            store.save(task)
            store.event(task_id, "clarified", {"goal": body.goal})
        return await engine.run(task_id)

    @app.post("/api/tasks/{task_id}/resume", dependencies=[worker_auth])
    async def resume(task_id: str):
        async with engine.lock:
            task = get_task(task_id)
            if task["status"] not in {"interrupted", "failed"} or task["steps"] >= settings.max_steps:
                raise HTTPException(409, "Only interrupted/failed tasks with remaining steps can resume")
            task["status"] = "interrupted"
            store.save(task)
            store.event(task_id, "resumed", {"remaining_steps": settings.max_steps - task["steps"]})
        return await engine.run(task_id)

    @app.get("/api/records", dependencies=[worker_auth])
    async def records():
        return await engine.request("GET", "/records")

    @app.get("/api/inbox", dependencies=[worker_auth])
    def inbox():
        return store.rows("inbox")

    @app.get("/api/approvals", dependencies=[worker_auth])
    def approvals():
        return store.rows("approvals")

    @app.post("/api/faults", dependencies=[reviewer_auth])
    def fault(body: FaultRequest):
        if not settings.enable_faults:
            raise HTTPException(403, "Set ENABLE_FAULTS=true to use sandbox fault injection")
        with store.connect() as db:
            db.execute(
                "INSERT INTO faults VALUES(?,?) ON CONFLICT(name) DO UPDATE SET remaining=excluded.remaining",
                (body.name, body.count),
            )
        return body.model_dump()

    return app
