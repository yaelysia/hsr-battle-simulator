from __future__ import annotations

import argparse
import json
import mimetypes
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .runner import UIRunOptions, UIRunner, load_json_file


PACKAGE_ROOT = Path(__file__).resolve().parent
STATIC_ROOT = PACKAGE_ROOT / "static"
CASES_ROOT = PACKAGE_ROOT / "cases"
CASE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


class V8UIRequestHandler(BaseHTTPRequestHandler):
    runner: UIRunner
    cases_root: Path

    server_version = "HSRV8UITestbench/0.1"

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlparse(self.path).path
        try:
            if path == "/api/health":
                self._send_json({"ok": True, "service": "simulator_v8_ui", "message": "服务已就绪", "report_schema": "v8_ui_report_v0_1"})
            elif path == "/api/catalog":
                self._send_json(self.runner.catalog())
            elif path == "/api/cases":
                self._send_json({"cases": self._list_cases()})
            elif path.startswith("/api/cases/"):
                case_id = _case_id(path.removeprefix("/api/cases/"))
                self._send_json(load_json_file(_scenario_path(self.cases_root, case_id)))
            elif path.startswith("/api/observations/"):
                case_id = _case_id(path.removeprefix("/api/observations/"))
                obs_path = _observations_path(self.cases_root, case_id)
                self._send_json(load_json_file(obs_path) if obs_path.exists() else {})
            else:
                self._serve_static(path)
        except FileNotFoundError as exc:
            self._send_error_json(HTTPStatus.NOT_FOUND, str(exc))
        except Exception as exc:  # pragma: no cover - HTTP boundary
            self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def do_PUT(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlparse(self.path).path
        try:
            if path.startswith("/api/cases/"):
                case_id = _case_id(path.removeprefix("/api/cases/"))
                data = self._read_json_body()
                scenario = data.get("scenario") if isinstance(data.get("scenario"), dict) else data
                if not isinstance(scenario, dict):
                    raise ValueError("测试用例内容必须是对象")
                _write_json(_scenario_path(self.cases_root, case_id), scenario)
                self._send_json({"ok": True, "case_id": case_id})
            elif path.startswith("/api/observations/"):
                case_id = _case_id(path.removeprefix("/api/observations/"))
                data = self._read_json_body()
                _write_json(_observations_path(self.cases_root, case_id), data)
                self._send_json({"ok": True, "case_id": case_id})
            else:
                self._send_error_json(HTTPStatus.NOT_FOUND, f"未知接口：{path}")
        except ValueError as exc:
            self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:  # pragma: no cover - HTTP boundary
            self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlparse(self.path).path
        try:
            if path != "/api/run":
                self._send_error_json(HTTPStatus.NOT_FOUND, f"未知接口：{path}")
                return
            data = self._read_json_body()
            scenario = data.get("scenario")
            if not isinstance(scenario, dict):
                raise ValueError("运行请求需要提供测试用例对象")
            options = UIRunOptions.from_dict(data.get("options") if isinstance(data.get("options"), dict) else None)
            observations = data.get("observations") if isinstance(data.get("observations"), dict) else {}
            report = self.runner.run_data(scenario, options=options, observations=observations)
            self._send_json(report)
        except ValueError as exc:
            self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception as exc:  # pragma: no cover - HTTP boundary
            self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[simulator_v8_ui] {self.address_string()} - {fmt % args}")

    def _read_json_body(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length")
        length = int(raw_length or "0")
        if length <= 0:
            return {}
        if length > 10_000_000:
            raise ValueError("请求内容过大")
        data = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("请求 JSON 根节点必须是对象")
        return data

    def _send_json(self, data: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_error_json(self, status: HTTPStatus, message: str) -> None:
        self._send_json({"ok": False, "error": message}, status=status)

    def _serve_static(self, raw_path: str) -> None:
        path = "/index.html" if raw_path in {"", "/"} else raw_path
        relative = Path(unquote(path).lstrip("/"))
        target = (STATIC_ROOT / relative).resolve()
        if STATIC_ROOT.resolve() not in (target, *target.parents):
            raise FileNotFoundError("静态文件路径超出允许范围")
        if not target.is_file():
            raise FileNotFoundError(path)
        content = target.read_bytes()
        content_type = mimetypes.guess_type(target.as_posix())[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _list_cases(self) -> list[dict[str, Any]]:
        self.cases_root.mkdir(parents=True, exist_ok=True)
        cases = []
        for path in sorted(self.cases_root.glob("*.scenario.json")):
            case_id = path.name.removesuffix(".scenario.json")
            item: dict[str, Any] = {
                "case_id": case_id,
                "path": path.as_posix(),
                "has_observations": _observations_path(self.cases_root, case_id).exists(),
            }
            try:
                data = load_json_file(path)
                item["scenario_id"] = data.get("scenario_id")
                item["version"] = data.get("version")
                item["unit_count"] = len(data.get("units", [])) if isinstance(data.get("units"), list) else 0
                item["route_count"] = len(data.get("route", [])) if isinstance(data.get("route"), list) else 0
            except Exception as exc:
                item["load_error"] = str(exc)
            cases.append(item)
        return cases


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="启动 v8 本地 UI 测试台。")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--cases-root", type=Path, default=CASES_ROOT)
    parser.add_argument("--tbgd-root", type=Path, default=None)
    args = parser.parse_args(argv)

    cases_root = args.cases_root.resolve()
    cases_root.mkdir(parents=True, exist_ok=True)
    V8UIRequestHandler.runner = UIRunner(tbgd_root=args.tbgd_root)
    V8UIRequestHandler.cases_root = cases_root
    server = ThreadingHTTPServer((args.host, args.port), V8UIRequestHandler)
    url = f"http://{args.host}:{args.port}"
    print(f"星穹铁道 v8 UI 测试台已启动：{url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n星穹铁道 v8 UI 测试台已停止")
    finally:
        server.server_close()
    return 0


def _case_id(value: str) -> str:
    case_id = unquote(value).strip("/")
    if not case_id or not CASE_ID_RE.match(case_id):
        raise ValueError("用例编号只能包含字母、数字、点、下划线和短横线")
    return case_id


def _scenario_path(root: Path, case_id: str) -> Path:
    return root / f"{case_id}.scenario.json"


def _observations_path(root: Path, case_id: str) -> Path:
    return root / f"{case_id}.observations.json"


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
