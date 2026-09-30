def test_pds_network_es_automatizacion():
    from detection.explicaciones import para_cluster, principal
    items = para_cluster(accounts=8, n_events=8, n_urls=0, content_similarity=95,
                         pds_network_count=7)
    d = {i["code"]: i["status"] for i in items}
    assert d["automated_non_malicious"] == "supported", d

def test_own_domain_syndication():
    from detection.explicaciones import para_cluster
    items = para_cluster(accounts=9, n_events=9, n_urls=9, content_similarity=99,
                         dominant_account_frac=0.2, own_domain_syndication=5)
    d = {i["code"]: i["status"] for i in items}
    assert d["syndicated_wire"] == "supported", d

def test_sin_senales_no_dispara():
    from detection.explicaciones import para_cluster
    items = para_cluster(accounts=2, n_events=2, content_similarity=10,
                         pds_network_count=0, own_domain_syndication=0)
    d = {i["code"]: i["status"] for i in items}
    assert d["automated_non_malicious"] == "ruled_out"
    assert d["syndicated_wire"] == "ruled_out"
