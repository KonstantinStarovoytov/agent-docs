from types import SimpleNamespace

from evals import run_evidence_coverage_experiment as runner


def test_baseline_only_flag_defaults_off() -> None:
    args = runner.parse_args([])
    assert args.baseline_only is False
    assert args.name_suffix == ""


def test_baseline_only_skips_iterative(monkeypatch) -> None:
    names: list[str] = []

    class FakeResult:
        def format(self) -> str:
            return ""

    class FakeDataset:
        def run_experiment(self, *, name, **_kwargs):
            names.append(name)
            return FakeResult()

    fake = SimpleNamespace(get_dataset=lambda _name: FakeDataset(), flush=lambda: None)
    monkeypatch.setattr(runner, "langfuse_client", lambda: fake)
    runner.main(["--baseline-only", "--name-suffix=-x"])
    assert names == ["evidence-coverage-baseline-v3-section-diverse-x"]
