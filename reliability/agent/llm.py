"""Language layer: GIDE only.

Ledger Lens talks to one model server: GIDE's local OpenAI-compatible API,
discovered from ~/.gide/server-port.json, authenticated with a key made by
`gide apikey create`. GIDE decides what sits behind it -- Ornith 9B on this
laptop, or its hosted Qwen in remote mode -- and that choice is invisible here.

Without a server or key the layer is simply offline. The deterministic engine
still produces every finding and the templated memo; the model only ever
ranks and writes, never calculates.

Configuration (any of these, first match wins):
    GIDE_BASE_URL   default http://127.0.0.1:<port from server-port.json>/v1
    GIDE_API_KEY    or a .env at the repo root, or ~/.gide/apikey
    GIDE_MODEL      default: the first id returned by /v1/models
    PRIORS_FORCE_OFFLINE=1   never call a model
"""

import json
import os
import urllib.error
import urllib.request

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_dotenv():
    """Minimal .env reader so nothing needs exporting in the shell."""
    for path in (os.path.join(_ROOT, ".env"), os.path.join(os.getcwd(), ".env")):
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip("'\""))
        except OSError:
            continue


def discover():
    """Return (base_url, api_key). Either may be None."""
    _load_dotenv()
    base = os.environ.get("GIDE_BASE_URL")
    if not base:
        try:
            with open(os.path.expanduser("~/.gide/server-port.json")) as f:
                base = f"http://127.0.0.1:{json.load(f)['port']}/v1"
        except (OSError, KeyError, ValueError):
            base = None
    key = os.environ.get("GIDE_API_KEY")
    if not key:
        for p in ("~/.gide/apikey", "~/.gide/api_key", "~/.gide/apikeys/default"):
            try:
                with open(os.path.expanduser(p)) as f:
                    key = f.read().strip()
                if key:
                    break
            except OSError:
                continue
    return (base.rstrip("/") if base else None), (key or None)


class LLM:
    def __init__(self, verbose=False):
        self.verbose = verbose
        self.base_url, self.api_key = discover()
        self.model = os.environ.get("GIDE_MODEL")
        self.calls = 0
        self.provider = None
        if os.environ.get("PRIORS_FORCE_OFFLINE") or not (self.base_url and self.api_key):
            return
        self.provider = "gide"
        if not self.model:
            self.model = self._first_model() or "default"

    @property
    def available(self):
        return self.provider is not None

    def describe(self):
        return f"gide:{self.model} @ {self.base_url}" if self.available else \
            "offline (deterministic narrative only)"

    # -- transport ---------------------------------------------------------
    def _request(self, path, body=None, timeout=180):
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"},
            method="POST" if body is not None else "GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if self.verbose:
                print(f"[llm] {path} -> HTTP {e.code}: {e.read()[:200]!r}")
        except Exception as e:                            # noqa: BLE001
            if self.verbose:
                print(f"[llm] {path} failed: {e}")
        return None

    def _first_model(self):
        d = self._request("/models", timeout=15)
        try:
            return d["data"][0]["id"]
        except (TypeError, KeyError, IndexError):
            return None

    # -- chat --------------------------------------------------------------
    def chat(self, system, messages, tools=None, max_tokens=4000, temperature=0.1):
        """Returns (text, tool_calls). tool_calls: [{id, name, input}]."""
        if not self.available:
            return None, []
        self.calls += 1
        msgs = [{"role": "system", "content": system}]
        for m in messages:
            c = m["content"]
            if isinstance(c, list):
                c = "\n".join(x.get("text", "") for x in c if isinstance(x, dict))
            msgs.append({"role": m["role"], "content": c})
        body = {"model": self.model, "messages": msgs, "max_tokens": max_tokens,
                "temperature": temperature}
        if tools:
            body["tools"] = [{"type": "function",
                              "function": {"name": t["name"], "description": t["description"],
                                           "parameters": t["input_schema"]}} for t in tools]
        d = self._request("/chat/completions", body)
        if not d:
            return None, []
        try:
            msg = d["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            return None, []
        calls = []
        for i, c in enumerate(msg.get("tool_calls") or []):
            try:
                calls.append({"id": c.get("id", f"call_{i}"), "name": c["function"]["name"],
                              "input": json.loads(c["function"].get("arguments") or "{}")})
            except (KeyError, ValueError):
                continue
        return (msg.get("content") or "").strip(), calls

    def json_object(self, system, prompt, fallback):
        """Ask for a JSON object; never let a parse failure break a run."""
        text, _ = self.chat(system + "\n\nRespond with a single JSON object and nothing else.",
                            [{"role": "user", "content": prompt}])
        if not text:
            return fallback
        s = text.strip()
        if s.startswith("```"):
            s = s.split("```")[1]
            s = s[4:] if s.startswith("json") else s
        for cand in (s.strip(), s[s.find("{"): s.rfind("}") + 1]):
            try:
                return json.loads(cand)
            except (json.JSONDecodeError, ValueError):
                continue
        return fallback
