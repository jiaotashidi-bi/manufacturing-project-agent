from __future__ import annotations

from datetime import date

import streamlit as st

from manufacturing_agent.audit import AuditStore
from manufacturing_agent.config import get_settings
from manufacturing_agent.models import ApprovalRequest, CompanyProfile
from manufacturing_agent.policy_intake import PolicyIntakeService
from manufacturing_agent.workflow import ManufacturingApplicationAgent

st.set_page_config(page_title="制造业项目申报 Agent", page_icon="🏭", layout="wide")
st.markdown(
    """
    <style>
    .block-container {padding-top: 1.6rem; padding-bottom: 3rem; max-width: 1500px;}
    [data-testid="stMetric"] {border: 1px solid #dce4ec; border-radius: 12px; padding: 14px;}
    div[data-testid="stStatusWidget"] {border-radius: 12px;}
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def services():
    settings = get_settings()
    workflow_agent = ManufacturingApplicationAgent(settings=settings)
    policy_intake = PolicyIntakeService(settings, workflow_agent.database)
    return settings, workflow_agent, policy_intake


settings, agent, intake = services()

st.title("制造业项目申报 Agent")
st.caption("政策接入与审核 → 企业匹配 → 材料检查 → 人工审批 → 可追溯导出")
st.warning("公开演示环境：仅可使用公开政策与虚构企业数据。系统不会执行真实申报或对外发送。")

with st.sidebar:
    st.subheader("当前身份")
    username = st.text_input("用户名", value=st.session_state.get("username", "demo-analyst"))
    role = st.selectbox("角色", ["analyst", "approver", "admin"], index=0)
    st.session_state["username"] = username
    st.caption(f"认证模式：{settings.auth_mode}｜模型：{settings.llm_provider}")
    st.divider()
    st.markdown("**权限说明**")
    st.caption("analyst 可评估和编辑；approver/admin 可审批与导出。生产环境应启用 OIDC。")

dashboard_tab, intake_tab, company_tab, approval_tab, search_tab = st.tabs(
    ["评估工作台", "政策接入与审核", "企业档案", "审批与导出", "证据检索"]
)

with dashboard_tab:
    companies = agent.list_companies()
    policies = agent.list_policies()
    company_labels = {company.id: company.name for company in companies}
    policy_labels = {policy.id: policy.title for policy in policies}

    st.subheader("申报预评估")
    with st.form("assessment_form"):
        col1, col2, col3 = st.columns([1.2, 2, 1])
        with col1:
            company_id = st.selectbox("虚构企业", list(company_labels), format_func=company_labels.get)
        with col2:
            policy_ids = st.multiselect(
                "政策项目", list(policy_labels), default=list(policy_labels), format_func=policy_labels.get
            )
        with col3:
            as_of = st.date_input("评估日期", value=date.today())
        start = st.form_submit_button("开始评估", type="primary", use_container_width=True)
    if start:
        if role not in {"analyst", "approver", "admin"}:
            st.error("当前角色无评估权限。")
        elif not policy_ids:
            st.error("请至少选择一个政策项目。")
        else:
            with st.spinner("正在执行规则检查、材料核验与草稿生成……"):
                run = agent.assess(company_id, policy_ids=policy_ids, as_of=as_of, actor=username)
            st.session_state["run_id"] = run.run_id
            st.success(f"评估完成，执行编号：{run.run_id}")

    run_id = st.session_state.get("run_id")
    if run_id:
        try:
            run = agent.store.load(run_id)
        except KeyError:
            run = None
        if run:
            eligible = sum(a.eligibility_status.value == "eligible" for a in run.assessments)
            missing = sum(
                m.status.value == "fail" for a in run.assessments for m in a.material_results
            )
            unknown = sum(len(a.missing_information) for a in run.assessments)
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("政策数量", len(run.assessments))
            c2.metric("条件匹配", eligible)
            c3.metric("缺失材料", missing)
            c4.metric("待补充信息", unknown)

            for assessment in run.assessments:
                with st.container(border=True):
                    st.markdown(f"### {assessment.policy_title}")
                    st.write(assessment.conclusion)
                    a, b, c = st.columns(3)
                    a.metric("申报窗口", assessment.window_status.value)
                    b.metric("资格判断", assessment.eligibility_status.value)
                    c.metric(
                        "一致性风险",
                        len([f for f in assessment.consistency_findings if f.severity != "info"]),
                    )
                    with st.expander("条件、材料与原文依据"):
                        st.dataframe(
                            [
                                {
                                    "条件": result.label,
                                    "结果": result.status.value,
                                    "企业值": result.actual,
                                    "期望值": result.expected,
                                    "依据": "；".join(
                                        f"{citation.title}｜{citation.locator}"
                                        for citation in result.citations
                                    ),
                                }
                                for result in assessment.rule_results
                            ],
                            use_container_width=True,
                            hide_index=True,
                        )
                        st.markdown("**材料清单**")
                        for material in assessment.material_results:
                            icon = "✅" if material.status.value == "pass" else "⚠️"
                            st.write(f"{icon} {material.label}：{material.reason}")
            with st.expander("申报材料初稿"):
                for policy_id, draft in run.application_drafts.items():
                    st.markdown(f"#### {policy_labels.get(policy_id, policy_id)}")
                    st.markdown(draft)
            with st.expander("审计轨迹与哈希链"):
                st.caption(f"完整性校验：{'通过' if AuditStore.verify(run) else '失败'}")
                st.dataframe(
                    [
                        {
                            "序号": event.sequence,
                            "时间": event.timestamp,
                            "事件": event.event_type,
                            "执行者": event.actor,
                            "前序哈希": event.previous_hash[:12],
                            "事件哈希": event.event_hash[:12],
                        }
                        for event in run.audit_events
                    ],
                    use_container_width=True,
                    hide_index=True,
                )
            if run.approval_status != "approved":
                st.info("当前为内部草稿。请在“审批与导出”页由 approver/admin 审批。")
    else:
        st.info("选择虚构企业和公开政策后开始评估。")

with intake_tab:
    st.subheader("公开政策接入")
    st.write("上传 PDF/DOCX 后生成结构化草稿；草稿不会直接进入评估库，必须经过审批。")
    with st.form("policy_upload"):
        uploaded = st.file_uploader("政策文件", type=["pdf", "docx"])
        c1, c2 = st.columns(2)
        title = c1.text_input("政策标题（可选）")
        issuer = c2.text_input("发布机关（可选）")
        source_url = st.text_input("公开来源网址", placeholder="https://官方站点/... ")
        confirmed_public = st.checkbox("我确认该文件为公开政策资料，且不含真实企业敏感数据")
        ingest_clicked = st.form_submit_button("生成审核草稿", type="primary")
    if ingest_clicked:
        if uploaded is None or not source_url:
            st.error("请选择文件并填写公开来源网址。")
        elif role not in {"analyst", "approver", "admin"}:
            st.error("当前角色无政策接入权限。")
        else:
            try:
                with st.spinner("正在提取文本和结构化候选项……"):
                    draft, version = intake.ingest(
                        uploaded.name,
                        uploaded.getvalue(),
                        source_url,
                        actor=username,
                        confirmed_public=confirmed_public,
                        title=title or None,
                        issuer=issuer or None,
                    )
                st.success(f"已生成 {draft.policy.id} 的第 {version} 版审核草稿。")
                for warning in draft.warnings:
                    st.warning(warning)
                st.json(draft.model_dump(mode="json"))
            except (PermissionError, ValueError, OSError) as exc:
                st.error(str(exc))

    st.divider()
    st.subheader("待审核政策版本")
    records = agent.database.list_policy_records()
    if not records:
        st.info("暂无上传草稿。仓库内置政策已经过人工校对。")
    for record in records:
        with st.expander(
            f"{record['policy']['title']}｜v{record['version']}｜{record['status']}"
        ):
            st.caption(
                f"创建人：{record['created_by']}｜来源哈希：{record['source_sha256'][:16]}…"
            )
            st.json(record["policy"])
            if record["status"] == "draft":
                c1, c2 = st.columns(2)
                if c1.button(
                    "批准进入政策库",
                    key=f"approve-policy-{record['policy_id']}-{record['version']}",
                    disabled=role not in {"approver", "admin"},
                    type="primary",
                ):
                    agent.database.review_policy(
                        record["policy_id"], record["version"], username, "approved"
                    )
                    st.success("政策版本已批准。")
                    st.rerun()
                if c2.button(
                    "驳回草稿",
                    key=f"reject-policy-{record['policy_id']}-{record['version']}",
                    disabled=role not in {"approver", "admin"},
                ):
                    agent.database.review_policy(
                        record["policy_id"], record["version"], username, "rejected"
                    )
                    st.warning("政策草稿已驳回。")
                    st.rerun()

with company_tab:
    st.subheader("虚构企业档案编辑器")
    companies = agent.list_companies()
    selected_company_id = st.selectbox(
        "选择企业", [company.id for company in companies], format_func=lambda cid: agent.get_company(cid).name
    )
    selected_company = agent.get_company(selected_company_id)
    edited_json = st.text_area(
        "企业结构化数据（JSON）",
        value=selected_company.model_dump_json(indent=2),
        height=500,
        help="公开演示模式会拒绝 fictional=false 的档案。",
    )
    if st.button("校验并保存企业档案", type="primary"):
        try:
            company = CompanyProfile.model_validate_json(edited_json)
            if not company.fictional:
                raise ValueError("公开演示模式仅允许 fictional=true")
            agent.database.save_company(company, username)
            st.success("企业档案已保存到数据库，并将用于后续评估。")
        except ValueError as exc:
            st.error(f"数据校验失败：{exc}")

with approval_tab:
    st.subheader("人工审批与文档导出")
    runs = agent.database.list_runs(limit=50)
    if not runs:
        st.info("暂无评估记录。")
    else:
        labels = {
            run.run_id: f"{run.company_name}｜{run.run_id}｜{run.approval_status}" for run in runs
        }
        selected_run_id = st.selectbox("选择执行记录", list(labels), format_func=labels.get)
        selected_run = agent.store.load(selected_run_id)
        st.write(selected_run.draft_markdown)
        decision = st.radio("审批决定", ["approved", "rejected"], horizontal=True)
        comment = st.text_input("审批意见")
        if st.button(
            "提交审批决定",
            disabled=role not in {"approver", "admin"},
            type="primary",
        ):
            agent.approve(
                selected_run_id,
                ApprovalRequest(reviewer=username, decision=decision, comment=comment),
                role=role,
            )
            st.success("审批结果已记录并写入审计链。")
            st.rerun()
        selected_run = agent.store.load(selected_run_id)
        if selected_run.approval_status == "approved" and role in {"approver", "admin"}:
            st.markdown("**导出已解锁**")
            columns = st.columns(3)
            for column, format_name, mime in zip(
                columns,
                ["md", "docx", "pdf"],
                [
                    "text/markdown",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "application/pdf",
                ],
                strict=True,
            ):
                path = agent.export_document(selected_run_id, role, format_name)
                column.download_button(
                    f"下载 {format_name.upper()}",
                    data=path.read_bytes(),
                    file_name=path.name,
                    mime=mime,
                    use_container_width=True,
                )
        else:
            st.info("审批通过后才可生成和下载正式导出文件。")

with search_tab:
    st.subheader("政策证据混合检索")
    with st.form("evidence_search"):
        query = st.text_input(
            "输入条件、金额、日期或材料名称", placeholder="例如：研发投入占营业收入比例"
        )
        top_k = st.slider("返回条数", 1, 10, 5)
        search_clicked = st.form_submit_button("检索公开依据", type="primary")
    if search_clicked and query:
        results = agent.retrieve(query, top_k=top_k)
        if not results:
            st.info("未找到足够相关的公开政策依据。")
        for result in results:
            with st.container(border=True):
                c1, c2 = st.columns([5, 1])
                c1.markdown(f"**{result.citation.title}｜{result.citation.locator}**")
                c2.metric("相关度", f"{result.score:.3f}")
                st.write(result.text)
                official = "是" if result.citation.official else "否"
                st.caption(f"来源：[查看原文]({result.citation.url})｜官方来源：{official}")
