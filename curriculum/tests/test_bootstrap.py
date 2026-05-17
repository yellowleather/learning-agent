from pathlib import Path

from typer.testing import CliRunner

from engine.cli import app
from curriculum.bootstrap import BootstrappedWorkspace, bootstrap_curriculum_workspace


runner = CliRunner()


class FakeAnthropicClient:
    def __init__(self):
        self.calls = []

    def generate_text(self, *, prompt, model, max_tokens, temperature):
        self.calls.append(
            {
                "prompt": prompt,
                "model": model,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
        )
        if len(self.calls) == 1:
            return """# 8-Week Plan

### Repository Structure
```text
demo_workspace/
├── docs/
├── server/
├── benchmarks/
└── runtime/
```
"""


def test_bootstrap_curriculum_workspace_uses_existing_empty_repo(monkeypatch, tmp_path):
    prompt_path = tmp_path / "curriculum" / "prompts" / "demo.md"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text("Generate a roadmap.")

    output_repo = tmp_path / "ai_inference_engineering"
    output_repo.mkdir()
    (output_repo / ".git").mkdir()

    initialized_repos = []

    def fake_initialize_git_repo(workspace_root: Path) -> None:
        initialized_repos.append(workspace_root)

    monkeypatch.setattr("curriculum.bootstrap._initialize_git_repo", fake_initialize_git_repo)

    client = FakeAnthropicClient()

    result = bootstrap_curriculum_workspace(
        repo_root=tmp_path,
        prompt_path=prompt_path,
        output_repo_path=output_repo,
        client=client,
    )

    assert Path(result.workspace_root) == output_repo
    assert initialized_repos == []
    assert (output_repo / "docs" / "8_week_plan.md").exists()
    assert (output_repo / "workspace_manifest.json").exists()
    assert not (output_repo / "server").exists()
    assert not (output_repo / "benchmarks").exists()
    assert not (output_repo / "runtime").exists()
    assert result.directories == []
    assert len(client.calls) == 1
    assert client.calls[0]["temperature"] == 0.8


def test_bootstrap_curriculum_workspace_sends_prompt_verbatim(monkeypatch, tmp_path):
    prompt_path = tmp_path / "curriculum" / "prompts" / "demo.md"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_body = "Exact prompt body.\nNo extra instructions."
    prompt_path.write_text(prompt_body)

    output_repo = tmp_path / "ai_inference_engineering"
    output_repo.mkdir()
    (output_repo / ".git").mkdir()

    client = FakeAnthropicClient()

    bootstrap_curriculum_workspace(
        repo_root=tmp_path,
        prompt_path=prompt_path,
        output_repo_path=output_repo,
        client=client,
    )

    assert len(client.calls) == 1
    assert client.calls[0]["prompt"] == prompt_body


def test_bootstrap_curriculum_workspace_does_not_create_dirs_from_repository_structure(monkeypatch, tmp_path):
    prompt_path = tmp_path / "curriculum" / "prompts" / "demo.md"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text("Generate a roadmap.")

    output_repo = tmp_path / "ai_inference_engineering"
    output_repo.mkdir()
    (output_repo / ".git").mkdir()

    class CommentTreeClient(FakeAnthropicClient):
        def generate_text(self, *, prompt, model, max_tokens, temperature):
            self.calls.append(
                {
                    "prompt": prompt,
                    "model": model,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                }
            )
            return """# Plan

### Repository Structure
```text
inference-server/
├── server/
│   ├── quantization.py     # INT8/INT4 quantization
│   └── api.py              # HTTP/gRPC serving endpoints
├── kernels/
└── configs/
```
"""

    monkeypatch.setattr("curriculum.bootstrap._initialize_git_repo", lambda _workspace_root: None)

    result = bootstrap_curriculum_workspace(
        repo_root=tmp_path,
        prompt_path=prompt_path,
        output_repo_path=output_repo,
        client=CommentTreeClient(),
    )

    assert result.directories == []
    assert not (output_repo / "server").exists()
    assert not (output_repo / "kernels").exists()
    assert not (output_repo / "configs").exists()
    assert not (output_repo / "api.py              # HTTP").exists()
    assert not (output_repo / "quantization.py     # INT8").exists()


def test_curriculum_bootstrap_cli_accepts_output_repo_path(monkeypatch, tmp_path):
    (tmp_path / "coach.config.json").write_text("{}\n")
    monkeypatch.chdir(tmp_path)

    captured = {}

    def fake_bootstrap(*, repo_root, prompt_path, output_repo_path, model):
        captured["repo_root"] = repo_root
        captured["prompt_path"] = prompt_path
        captured["output_repo_path"] = output_repo_path
        captured["model"] = model
        return BootstrappedWorkspace(
            workspace_root=str(tmp_path / "ai_inference_engineering"),
            plan_path=str(tmp_path / "ai_inference_engineering" / "docs" / "8_week_plan.md"),
            prompt_path=str(prompt_path),
            model=model,
            directories=[],
        )

    monkeypatch.setattr("engine.cli.bootstrap_curriculum_workspace", fake_bootstrap)

    result = runner.invoke(app, ["curriculum", "bootstrap", "--output-repo-path", "ai_inference_engineering"])

    assert result.exit_code == 0
    assert "Created workspace:" in result.stdout
    assert captured["repo_root"] == tmp_path
    assert captured["output_repo_path"] == Path("ai_inference_engineering")
    assert captured["prompt_path"] == tmp_path / "curriculum" / "prompts" / "ai_inference_engineering_8_week_plan.md"
