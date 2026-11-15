import pytest
from api_helpers import Q

from pxs.api.config import ConfigError, from_env
from pxs.api.params import ParamError, parse_view


def view(**q):
    return parse_view({**Q, **q}.items())


@pytest.mark.parametrize("query, needle", [
    ({"ra": "360.5"}, "'ra' must be between 0 and 360"),
    ({"ra": "-1"}, "'ra' must be between 0 and 360"),
    ({"dec": "90.01"}, "'dec' must be between -90 and 90"),
    ({"dec": "nan"}, "finite"),
    ({"ra": "inf"}, "finite"),
    ({"ra": "abc"}, "'ra' must be a number"),
    ({"pmra": "100"}, "both 'pmra' and 'pmdec'"),
    ({"pmra": "20000", "pmdec": "0"}, "under 20000"),
    ({"pmra": "0", "pmdec": "-25000"}, "under 20000"),
    ({"epoch": "1989.9"}, "a year from 1990 to 2035"),
    ({"epoch": "2035.1"}, "a year from 1990 to 2035"),
    ({"fov": "60"}, "'fov' must be between 120 and 480"),
    ({"fov": "1000"}, "'fov' must be between 120 and 480"),
    ({"name": "x" * 81}, "at most 80"),
    ({"name": "<script>"}, "'name' may contain only"),
    ({"bogus": "1"}, "Unknown parameter 'bogus'"),
])
def test_each_rule_rejects_with_a_clear_message(query, needle) -> None:
    with pytest.raises(ParamError, match=needle):
        view(**query)


def test_required_and_repeated() -> None:
    with pytest.raises(ParamError, match="required"):
        parse_view([("ra", "10")])
    with pytest.raises(ParamError, match="more than once"):
        parse_view([("ra", "10"), ("dec", "1"), ("ra", "11")])


def test_normalisation_and_key() -> None:
    a = view(ra="150.012301", pmra="10.04", pmdec="-3.01", epoch="2016.0004", fov="250")
    assert (a.ra, a.pmra, a.pmdec, a.epoch, a.fov) == (150.0123, 10.0, -3.0, 2016.0, 240.0)
    assert a.key == view(ra="150.0123", pmra="10", pmdec="-3", epoch="2016", fov="240").key
    assert len(a.key) == 64 and int(a.key, 16) >= 0
    assert view(ra="359.999999").ra == 0.0
    assert view(fov="300").fov == 240.0 and view(fov="301").fov == 360.0
    # epoch only matters with proper motion; the name never changes the view
    assert view(epoch="2000").key == view(epoch="2020").key == view(name="Foo").key
    assert view(pmra="1", pmdec="1", epoch="2000").key != view(pmra="1", pmdec="1").key
    assert view(name=" WISE 0855-0714 ").name == "WISE 0855-0714"


def test_env_settings() -> None:
    s = from_env({"PXS_MAX_BUILDS": "3", "PXS_ALLOWED_ORIGINS": "https://a.org, https://b.org/",
                  "PXS_TRUST_PROXY": "1", "PXS_CACHE_MAX_MB": "10"})
    assert s.max_builds == 3 and s.trust_proxy and s.cache_max_bytes == 10 * 1024**2
    assert s.allowed_origins == ("https://a.org", "https://b.org")
    assert from_env({}).allowed_origins == () and from_env({}).build_timeout_s == 240.0
    for bad in ({"PXS_ALLOWED_ORIGINS": "*"}, {"PXS_MAX_BUILDS": "0"},
                {"PXS_BUILD_TIMEOUT_S": "x"}):
        with pytest.raises(ConfigError):
            from_env(bad)


def test_api_rejects_with_422(make_client) -> None:
    client, _ = make_client()
    r = client.get("/api/view", params={**Q, "dec": "-91"})
    assert r.status_code == 422
    assert "'dec' must be between" in r.json()["error"]
    assert client.get("/api/view", params={**Q, "callback": "x"}).status_code == 422
