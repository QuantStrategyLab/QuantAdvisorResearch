from copy import deepcopy

import pytest
from test_publisher import build_sample_report

from quant_advisor_research.contracts import validate_advisory_report
from quant_advisor_research.publisher import render_index_html


def empty_report():
    report = deepcopy(build_sample_report())
    report['final_decisions']['recommendations'] = []
    report['final_decisions']['horizon_buckets'] = {'long': [], 'medium': [], 'short': []}
    report['final_decisions']['horizon_rankings'] = {
        name: [{'symbol': 'CANDIDATE', 'action': 'watch', 'score': 0.1}]
        for name in ('long', 'medium', 'short')
    }
    report['summary']['data_quality_warnings'] = []
    report['generated_at'] = '2026-05-31T12:00:00Z'
    report['expires_at'] = '2026-06-07T12:00:00Z'
    report['source_artifacts']['ai_signal'] = 'synthetic/ai_signal.json'
    report['source_artifacts']['theme_momentum'] = 'synthetic/theme_momentum.json'
    report['freshness'] = {
        name: {'present': True, 'valid': True, 'reason': 'fresh',
               'as_of': '2026-05-30', 'generated_at': '2026-05-30T00:00:00Z',
               'expires_at': '2026-06-06T00:00:00Z'}
        for name in ('ai_signal', 'theme_momentum')
    }
    validate_advisory_report(report)
    return report


def test_complete_empty_report_explains_threshold_without_promoting_watch_candidates():
    page = render_index_html([empty_report()])
    assert page.count('本期无推荐') == 3
    assert page.count('候选未达到推荐门槛。') == 3
    assert '空结果也是结论：说明信号未达门槛，而不是数据缺失。' in page
    assert 'CANDIDATE' not in page
    assert '<a href="index.html" aria-current="page">最新</a>' in page
    assert '>方法说明</a>' in page
    assert '>RSS</a>' in page


def test_empty_result_with_data_warning_does_not_claim_complete_inputs():
    report = empty_report()
    report['summary']['data_quality_warnings'] = ['missing_market_confirmation']
    page = render_index_html([report])
    assert '不是数据缺失' not in page
    assert '输入数据状态和未达门槛的原因请见完整报告。' in page
    assert '候选未达到推荐门槛' not in page
    report['summary']['data_quality_warnings'] = []
    report['freshness'] = {'ai_signal': {'valid': False, 'reason': 'not_provided'}}
    assert '不是数据缺失' not in render_index_html([report])


@pytest.mark.parametrize('freshness', [{}, None, {'ai_signal': {}},
    {'ai_signal': {'present': True, 'reason': 'fresh'},
     'theme_momentum': {'present': True, 'valid': True, 'reason': 'fresh'}}])
def test_unknown_freshness_never_asserts_complete_inputs_or_threshold(freshness):
    report = empty_report()
    report['freshness'] = freshness
    page = render_index_html([report])
    assert '不是数据缺失' not in page
    assert '候选未达到推荐门槛' not in page
    assert page.count('具体原因见完整报告。') == 3


def test_valid_legacy_schema_with_no_freshness_keeps_reason_unknown():
    report = empty_report()
    report.update(schema_version='5', contract_version='model_recommendations.v5')
    for key in ('reference_time', 'expires_at', 'freshness', 'input_digest'):
        report.pop(key)
    validate_advisory_report(report)
    page = render_index_html([report])
    assert '不是数据缺失' not in page
    assert '候选未达到推荐门槛' not in page


@pytest.mark.parametrize('rankings', [None, [], {'long': [None]}, {'long': [{'action': None}]}])
def test_unvalidated_ranking_metadata_cannot_invent_a_reason_or_break_the_page(rankings):
    report = empty_report()
    report['final_decisions']['horizon_rankings'] = rankings
    validate_advisory_report(report)
    page = render_index_html([report])
    assert '不是数据缺失' not in page
    assert '候选未达到推荐门槛' not in page


def test_nonempty_report_keeps_actual_symbols_and_does_not_claim_all_empty():
    page = render_index_html([build_sample_report()])
    assert 'MU' in page and 'NVDA' in page
    assert '本期三个周期均未产生合格推荐' not in page


def test_missing_ranking_evidence_does_not_invent_a_threshold_reason():
    report = empty_report()
    report['final_decisions']['horizon_rankings'] = {}
    page = render_index_html([report])
    assert '不是数据缺失' not in page
    assert '候选未达到推荐门槛' not in page
    assert page.count('具体原因见完整报告。') == 3


def test_report_symbols_are_escaped_and_missing_reports_have_no_fake_date():
    report = build_sample_report()
    report['final_decisions']['recommendations'][0]['symbol'] = '<script>alert(1)</script>'
    page = render_index_html([report])
    assert '<script>alert(1)</script>' not in page
    assert '&lt;script&gt;' in page
    empty = render_index_html([])
    assert '暂无报告' in empty
    assert '<time ' not in empty
    assert '本期无推荐' not in empty
