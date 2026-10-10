from __future__ import annotations
import json
import time
import statistics
import hashlib
from arvectum_data.engine import RawAsset, SemanticHTMLRecordProvider


def generate(n):
    blocks = []
    for i in range(n):
        blocks.append(
            f'<article class="offer"><div class="card"><h3>Скидка {i % 95}% на всё</h3><p>Ограниченный срок действия купона для гостей {i}.</p><a href="/go?offer_id={i}">Показать промокод</a></div></article>'
        )
    return "<main>" + "".join(blocks) + "</main>"


for n in (30, 100, 200):
    asset = RawAsset(
        asset_id="perf-page", source_url="https://example.test/offers", html=generate(n)
    )
    provider = SemanticHTMLRecordProvider(max_records=n + 10)
    times = []
    payload = None
    for _ in range(3):
        t = time.perf_counter()
        result = provider.records(asset, ())
        times.append(1000 * (time.perf_counter() - t))
        obj = [
            (x.record_id, x.source_ref, x.asset.attributes, x.asset.text) for x in result.records
        ]
        fingerprint = hashlib.sha256(
            json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str).encode()
        ).hexdigest()
        assert payload is None or payload == fingerprint
        payload = fingerprint
    print(
        f"n={n} median_ms={statistics.median(times):.1f} records={len(result.records)} fingerprint={payload}",
        flush=True,
    )
