from datetime import date

import streamlit as st

from manufacturing_agent.workflow import ManufacturingApplicationAgent


st.set_page_config(page_title="制造业项目申报 Agent", page_icon="🏭", layout="wide")
agent = ManufacturingApplicationAgent()
companies = agent.repository.list_companies()
policies = agent.list_policies()

st.title("制造业项目申报 Agent")
st.caption("公开政策 × 虚构企业数据 × 条件规则 × 原文引用 × 人工审批")
st.warning("演示系统不执行真实申报，不上传或处理真实企业敏感材料。")

company_labels = {company.id: company.name for company in companies}
policy_labels = {policy.id: policy.title for policy in policies}

with st.sidebar:
    st.header("评估设置")
    company_id = st.selectbox("虚构企业", company_labels, format_func=company_labels.get)
    policy_ids = st.multiselect(
        "政策项目",
        policy_labels,
        default=list(policy_labels),
        format_func=policy_labels.get,
    )
    as_of = st.date_input("评估日期", value=date(2026, 8, 10))
    start = st.button("开始评估", type="primary", use_container_width=True)

if start:
    run = agent.assess(company_id, policy_ids=policy_ids, as_of=as_of, actor="streamlit_user")
    st.session_state["run"] = run

run = st.session_state.get("run")
if not run:
    st.info("从左侧选择企业和政策，然后开始评估。")
else:
    st.success(f"评估完成，执行编号：{run.run_id}")
    for assessment in run.assessments:
        st.subheader(assessment.policy_title)
        c1, c2, c3 = st.columns(3)
        c1.metric("申报窗口", assessment.window_status.value)
        c2.metric("条件判断", assessment.eligibility_status.value)
        c3.metric(
            "缺失材料",
            sum(item.status.value == "fail" for item in assessment.material_results),
        )
        st.write(assessment.conclusion)
        with st.expander("条件、材料和引用明细"):
            st.dataframe(
                [
                    {
                        "条件": result.label,
                        "结果": result.status.value,
                        "企业值": result.actual,
                        "依据": "；".join(c.locator for c in result.citations),
                    }
                    for result in assessment.rule_results
                ],
                use_container_width=True,
            )
            for material in assessment.material_results:
                st.write(f"- {material.status.value}: {material.label} — {material.reason}")
    with st.expander("执行轨迹"):
        st.json([event.model_dump(mode="json") for event in run.audit_events])
    with st.expander("申报预评估草稿"):
        st.markdown(run.draft_markdown)
    for policy_id, draft in run.application_drafts.items():
        with st.expander(f"申报材料初稿：{policy_labels.get(policy_id, policy_id)}"):
            st.markdown(draft)
    st.error("正式导出被权限门禁阻止：需要 approver/admin 人工审批。")
