from pathlib import Path


def test_platform_package_does_not_import_discount_product() -> None:
    package_root = Path(__file__).parents[1] / "src" / "arvectum_data"
    offenders: list[str] = []

    for path in package_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "from src." in text or "import src." in text:
            offenders.append(str(path.relative_to(package_root)))

    assert offenders == []
