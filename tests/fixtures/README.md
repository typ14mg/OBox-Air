# Offline source-format fixtures

`onebox_point.html` is a minimal HTML reconstruction containing the public point
identity, address and measurement fields observed in the initial HTTP response
from [the Allegro One map](https://allegro.pl/kampania/one/znajdz-nas?pointId=1522606)
on 27 October 2026. It retains only fields consumed by the parser. The unrelated
JSON-LD script verifies that the parser chooses the appropriate JSON script.
Descriptions, opening times, photographs and the rest of the page are omitted.
The fixed historical values are test data, not a current air-quality report.

Map API tests use small synthetic responses shaped like the observed
`points`, `clusters` and `metadata` response. They contain no copied map catalogue
and make no claim about the presence of a current measurement at a given point.
