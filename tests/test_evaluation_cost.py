from app.evaluation.cost import build_cost_report, estimate_cost, record_tokens


def test_estimate_cost_uses_per_1k_prices() -> None:
    cost = estimate_cost(
        prompt_tokens=1000,
        completion_tokens=2000,
        prompt_price_per_1k=0.5,
        completion_price_per_1k=1.0,
    )
    assert cost["prompt_cost"] == 0.5
    assert cost["completion_cost"] == 2.0
    assert cost["total_cost"] == 2.5


def test_record_tokens_prefers_real_usage() -> None:
    record = {
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "completion_tokens_details": {"reasoning_tokens": 30},
        },
        "estimated_prompt_tokens": 999,
        "estimated_answer_tokens": 999,
    }
    assert record_tokens(record) == (100, 50, 30)


def test_record_tokens_falls_back_to_estimated() -> None:
    record = {"estimated_prompt_tokens": 12, "estimated_answer_tokens": 8}
    assert record_tokens(record) == (12, 8, 0)


def test_build_cost_report_aggregates_usage_and_retries() -> None:
    eval_report = {
        "summary": {"avg_latency_ms": 9810.0},
        "records": [
            {
                "status_code": 200,
                "attempts": 1,
                "usage": {
                    "prompt_tokens": 1000,
                    "completion_tokens": 500,
                    "completion_tokens_details": {"reasoning_tokens": 400},
                },
            },
            {
                "status_code": 200,
                "attempts": 2,
                "usage": {
                    "prompt_tokens": 1000,
                    "completion_tokens": 500,
                    "completion_tokens_details": {"reasoning_tokens": 400},
                },
            },
        ],
    }

    report = build_cost_report(
        eval_report,
        prompt_price_per_1k=1.0,
        completion_price_per_1k=2.0,
    )

    assert report["token_source"] == "real_usage"
    assert report["total_questions"] == 2
    assert report["total_calls"] == 3
    assert report["retry_calls"] == 1
    assert report["success_calls"] == 2
    assert report["total_prompt_tokens"] == 2000
    assert report["total_completion_tokens"] == 1000
    assert report["total_reasoning_tokens"] == 800
    assert report["total_tokens"] == 3000
    assert report["prompt_cost"] == 2.0
    assert report["completion_cost"] == 2.0
    assert report["total_cost"] == 4.0
    assert report["avg_cost_per_question"] == 2.0
    assert report["avg_cost_per_call"] == round(4.0 / 3, 6)
    assert report["retry_cost"] == round(round(4.0 / 3, 6) * 1, 6)


def test_build_cost_report_uses_estimated_when_no_usage() -> None:
    eval_report = {
        "summary": {},
        "records": [
            {
                "status_code": 200,
                "attempts": 1,
                "estimated_prompt_tokens": 100,
                "estimated_answer_tokens": 50,
            }
        ],
    }

    report = build_cost_report(eval_report)

    assert report["token_source"] == "estimated"
    assert report["total_prompt_tokens"] == 100
    assert report["total_completion_tokens"] == 50
    assert report["total_cost"] == 0.0
