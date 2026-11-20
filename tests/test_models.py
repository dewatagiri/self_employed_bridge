from self_employed_bridge.models import Exposure, Job


def test_exposure_from_dict_ignores_unknown():
    e = Exposure.from_dict({"borrower_live_amount": 5, "live_job_ids": ["a"], "junk": 1})
    assert e.borrower_live_amount == 5 and e.live_job_ids == ("a",)


def test_job_from_dict(make_job):
    j = make_job()
    assert Job.from_dict(j.__dict__) == j
