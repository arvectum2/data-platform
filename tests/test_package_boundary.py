from pathlib import Path


def test_platform_package_does_not_import_discount_product() -> None:
    package_root = Path(__file__).parents[1] / "src" / "arvectum_data"
    offenders: list[str] = []

    for path in package_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "from src." in text or "import src." in text:
            offenders.append(str(path.relative_to(package_root)))

    assert offenders == []


def test_platform_source_has_no_tender_agent_imports() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "arvectum_data"
    forbidden = ("src.tender_research", "tender_agent", "tender_research")
    violations: list[str] = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if any(token in text for token in forbidden):
            violations.append(str(path.relative_to(root)))
    assert violations == []
