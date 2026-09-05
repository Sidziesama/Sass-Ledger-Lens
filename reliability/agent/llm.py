"""Provider-agnostic language layer.

Three modes, in preference order:
  1. Claude via the official Anthropic SDK  (ANTHROPIC_API_KEY)
  2. Any OpenAI-compatible endpoint         (PRIORS_LOCAL_BASE_URL) -- this is
     how GIDE's local Ornith 9B is used, so the whole agent runs air-gapped
  3. No model at all                        -- the deterministic engine still
     produces the full finding set and a templated narrative

Mode 3 matters: the numbers never depend on a model being reachable. The model
ranks and writes; it never calculates.
"""

import json
import os
import urllib.request

MODEL = os.environ.get("PRIORS_MODEL", "claude-opus-5")


class LLM:
    def __init__(self, verbose=False):
        self.verbose = verbose
        self.provider = None
        self.model = MODEL
        self.calls = 0
        self._client = None

        if os.environ.get("PRIORS_FORCE_OFFLINE"):
            return
        if os.environ.get("PRIORS_LOCAL_BASE_URL"):
            self.provider = "local"
            self.base_url = os.environ["PRIORS_LOCAL_BASE_URL"].rstrip("/")
            self.model = os.environ.get("PRIORS_LOCAL_MODEL", "ornith-1.0")
            return
        if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
            try:
                import anthropic
                self._client = anthropic.Anthropic()
                self.provider = "anthropic"
            except Exception as e:                       # noqa: BLE001
                if verbose:
                    print(f"[llm] anthropic unavailable: {e}")

    @property
    def available(self):
        return self.provider is not None

    def describe(self):
        if not self.available:
            return "offline (deterministic narrative only)"
        return f"{self.provider}:{self.model}"

    # -- chat ----------------------------------------------------------------
    def chat(self, system, messages, tools=None, max_tokens=8000):
        """Returns (text, tool_calls). tool_calls is a list of {id,name,input}."""
        if not self.available:
            return None, []
        self.calls += 1
        if self.provider == "anthropic":
            return self._anthropic(system, messages, tools, max_tokens)
        return self._openai_compatible(system, messages, tools, max_tokens)

    def _anthropic(self, system, messages, tools, max_tokens):
        kwargs = dict(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            thinking={"type": "adaptive"},
            output_config={"effort": "high"},
            # Opus 5 safety classifiers can decline; route around it rather than
            # letting a demo die on a refusal.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if tools:
            kwargs["tools"] = tools
        with self._client.beta.messages.stream(**kwargs) as stream:
            resp = stream.get_final_message()

        if getattr(resp, "stop_reason", None) == "refusal":
            return None, []
        text, calls = [], []
        for b in resp.content:
            if b.type == "text":
                text.append(b.text)
            elif b.type == "tool_use":
                calls.append({"id": b.id, "name": b.name, "input": b.input})
        return "\n".join(text).strip(), calls

    def _openai_compatible(self, system, messages, tools, max_tokens):
        """GIDE local Ornith, or any OpenAI-shaped server."""
        msgs = [{"role": "system", "content": system}]
        for m in messages:
            c = m["content"]
            if isinstance(c, list):
                c = "\n".join(x.get("text", "") for x in c if isinstance(x, dict))
            msgs.append({"role": m["role"], "content": c})
        body = {"model": self.model, "messages": msgs, "max_tokens": max_tokens,
                "temperature": 0.2}
        if tools:
            body["tools"] = [{"type": "function",
                              "function": {"name": t["name"],
                                           "description": t["description"],
                                           "parameters": t["input_schema"]}}
                             for t in tools]
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {os.environ.get('PRIORS_LOCAL_API_KEY', 'local')}"})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.loads(r.read())
        except Exception as e:                            # noqa: BLE001
            if self.verbose:
                print(f"[llm] local endpoint failed: {e}")
            return None, []
        msg = d["choices"][0]["message"]
        calls = [{"id": c.get("id", f"call_{i}"), "name": c["function"]["name"],
                  "input": json.loads(c["function"]["arguments"] or "{}")}
                 for i, c in enumerate(msg.get("tool_calls") or [])]
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
        try:
            return json.loads(s.strip())
        except json.JSONDecodeError:
            i, j = s.find("{"), s.rfind("}")
            if i >= 0 and j > i:
                try:
                    return json.loads(s[i:j + 1])
                except json.JSONDecodeError:
                    pass
        return fallback
