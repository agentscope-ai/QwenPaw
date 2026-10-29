# -*- coding: utf-8 -*-
"""The existing local-model management API, owned by the plugin."""

import json
from dataclasses import asdict
from functools import wraps

from pydantic import BaseModel, Field, ValidationError
from qwenpaw.plugins import PluginBusyError, SDKError
from qwenpaw.plugins.apps import HttpResponse, PawApp

from .io_helpers import run_io
from .model_types import DownloadSource


class StartServerRequest(BaseModel):
    model_id: str


class StartModelDownloadRequest(BaseModel):
    model_name: str
    source: DownloadSource = DownloadSource.AUTO


class ConfigRequest(BaseModel):
    max_context_length: int | None = Field(default=None, ge=32768)
    port: int | None = Field(default=None, ge=1, le=65535)
    generate_kwargs: dict | None = None


class DownloadProgress(BaseModel):
    status: str
    model_name: str | None = None
    downloaded_bytes: int
    total_bytes: int | None = None
    speed_bytes_per_sec: float
    source: str | None = None
    error: str | None = None
    local_path: str | None = None


class ApiError(Exception):
    def __init__(self, status, detail):
        super().__init__(detail)
        self.status = status
        self.detail = detail


# Management routes share one provider and response conversion.
# pylint: disable-next=too-many-statements
def create_app(provider):
    app = PawApp("Local models", app_id="local-models")
    run_sync = run_io

    def route(path, methods=("GET",), *, body=None):
        def decorate(handler):
            @wraps(handler)
            async def endpoint(_context, request):
                try:
                    payload = (
                        body.model_validate(request.json())
                        if body
                        else request
                    )
                    return await handler(payload, await provider.manager())
                except ValidationError as exc:
                    details = json.loads(exc.json(include_url=False))
                    for detail in details:
                        detail["loc"] = ["body", *detail["loc"]]
                    return HttpResponse({"detail": details}, status=422)
                except json.JSONDecodeError as exc:
                    return HttpResponse(
                        {
                            "detail": [
                                {
                                    "type": "json_invalid",
                                    "loc": ["body", exc.pos],
                                    "msg": "JSON decode error",
                                    "input": {},
                                    "ctx": {"error": exc.msg},
                                },
                            ],
                        },
                        status=422,
                    )
                except PluginBusyError as exc:
                    return HttpResponse({"detail": exc.detail}, status=409)
                except ApiError as exc:
                    return HttpResponse(
                        {"detail": exc.detail},
                        status=exc.status,
                    )

            app.route(path, methods=methods)(endpoint)
            return handler

        return decorate

    @route("/server")
    async def server_status(_request, manager):
        installable, install_message = await run_sync(
            manager.check_installability,
        )
        result = {
            "available": False,
            "installable": installable,
            "installed": False,
            "port": None,
            "model_name": None,
            "message": None,
        }
        if not installable:
            result["message"] = (
                install_message
                or "Current environment does not support llama.cpp"
            )
            return result
        installed, message = await run_sync(manager.check_installation)
        result["installed"] = installed
        if not installed:
            result["message"] = message or install_message
            return result
        state = await run_sync(manager.get_server_status)
        ready = False
        if state["running"] and await run_sync(
            manager.is_server_transitioning,
        ):
            message = "llama.cpp server is starting"
        elif state["running"]:
            try:
                ready = await manager.server_ready(timeout=3.0)
            except RuntimeError as exc:
                message = str(exc)
            except ValueError:
                message = "llama.cpp server status is temporarily unavailable"
        else:
            message = (
                "llama.cpp server is not running, "
                "please start the server first"
            )
        if state["running"] and not ready and not message:
            message = "llama.cpp server is not responding"
        result.update(
            available=installed and ready,
            port=state["port"],
            model_name=state["model_name"],
            message=message,
        )
        return result

    @route("/server/update")
    async def has_update(_request, manager):
        installable, _ = await run_sync(manager.check_installability)
        if not installable:
            return {"has_update": False}
        installed, _ = await run_sync(manager.check_installation)
        return {"has_update": installed and await manager.has_update()}

    @route("/server/download", ("POST",))
    async def install(_request, _manager):
        try:
            await provider.start_runtime_download()
        except (RuntimeError, ValueError) as exc:
            raise ApiError(409, str(exc)) from exc
        return {"status": "accepted", "message": "llama.cpp download started"}

    @route("/server/download")
    async def installation_progress(_request, manager):
        return DownloadProgress.model_validate(
            await run_sync(manager.get_runtime_download_progress),
        ).model_dump(mode="json")

    @route("/server/download", ("DELETE",))
    async def cancel_installation(_request, _manager):
        await provider.cancel_runtime_download()
        return {
            "status": "ok",
            "message": "llama.cpp download cancellation requested",
        }

    @route("/server", ("POST",), body=StartServerRequest)
    async def start(payload, _manager):
        try:
            result = await provider.ensure_server(payload.model_id)
            await provider.handle.select(result.model_info.id)
        except PluginBusyError:
            raise
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            raise ApiError(400, str(exc)) from exc
        return {
            "port": result.port,
            "model_info": {
                "source": "builtin",
                **{
                    key: value
                    for key, value in asdict(result.model_info).items()
                    if key not in {"size_bytes", "downloaded", "source"}
                },
            },
        }

    @route("/server", ("DELETE",))
    async def stop(_request, _manager):
        await provider.stop_server()
        return {"status": "ok", "message": "llama.cpp server stopped"}

    @route("/models")
    async def models(_request, manager):
        listed = {
            model.id: model
            for model in await run_sync(manager.get_recommended_models)
        }
        for model in await run_sync(manager.list_downloaded_models):
            listed.setdefault(model.id, model)
        return [asdict(model) for model in listed.values()]

    @route("/models/download", ("POST",), body=StartModelDownloadRequest)
    async def download(payload, _manager):
        try:
            await provider.start_model_download(
                payload.model_name,
                source=payload.source,
            )
        except RuntimeError as exc:
            raise ApiError(409, str(exc)) from exc
        except ValueError as exc:
            raise ApiError(400, str(exc)) from exc
        return {
            "status": "accepted",
            "message": f"Local model download started: {payload.model_name}",
        }

    @route("/models/download")
    async def download_progress(_request, manager):
        progress = await run_sync(manager.get_model_download_progress)
        return DownloadProgress.model_validate(progress).model_dump(
            mode="json",
        )

    @route("/models/download", ("DELETE",))
    async def cancel_download(_request, _manager):
        await provider.cancel_model_download()
        return {
            "status": "ok",
            "message": "Local model download cancellation requested",
        }

    @route("/models/{model_id:path}", ("DELETE",))
    async def delete(request, _manager):
        model_id = request.path_params["model_id"]
        try:
            await provider.remove_downloaded_model(model_id)
        except SDKError as exc:
            raise ApiError(409, str(exc)) from exc
        except ValueError as exc:
            raise ApiError(404, str(exc)) from exc
        return {"status": "ok", "message": f"Local model deleted: {model_id}"}

    @route("/config", ("PUT",), body=ConfigRequest)
    async def configure(payload, manager):
        if payload.max_context_length is not None:
            await manager.set_max_context_length(payload.max_context_length)
        if "port" in payload.model_fields_set:
            await manager.set_port(payload.port)
        if payload.generate_kwargs is not None:
            await provider.handle.update(
                generate_kwargs=payload.generate_kwargs,
            )
        return {"status": "ok", "message": "Local model settings updated"}

    @route("/config")
    async def configuration(_request, manager):
        return asdict(await run_sync(manager.get_config))

    return app
