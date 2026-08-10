from __future__ import annotations

from typing import Any

from .eligibility import MISSING, get_fact
from .models import CompanyProfile, Policy


def display(value: Any, unit: str = "") -> str:
    if value is MISSING or value is None or value == "":
        return "[待补充/核验]"
    return f"{value}{unit}"


class ApplicationDraftBuilder:
    """Fact-bound drafting: unknown facts become explicit placeholders, never guesses."""

    def build(self, policy: Policy, company: CompanyProfile) -> str:
        if policy.id == "smart_factory_excellent_2026":
            return self._smart_factory(company)
        if policy.id == "little_giant_batch_8_2026":
            return self._little_giant(company)
        return "# 申报材料初稿\n\n[该项目暂未配置专用模板]"

    @staticmethod
    def _smart_factory(company: CompanyProfile) -> str:
        facts = company.facts
        main_product = display(get_fact(facts, "business.main_product"))
        completion = display(get_fact(facts, "factory.completion_date"))
        cmm = display(get_fact(facts, "factory.cmm_level"), "级")
        ai_ratio = display(get_fact(facts, "factory.ai_scene_ratio"), "%")
        return "\n".join(
            [
                "# 卓越级智能工厂项目申报材料初稿",
                "",
                "> 仅使用虚构企业档案中的已知事实生成；方括号内容必须由人工补充并核验。",
                "",
                "## 一、申报单位基本信息",
                "",
                f"申报单位：{company.name}",
                f"主导产品：{main_product}",
                "企业地址、性质、行业代码、联系人：[待补充/核验]",
                "",
                "## 二、智能工厂基本信息",
                "",
                f"工厂建成日期：{completion}",
                f"当前获评层级：{display(get_fact(facts, 'factory.current_level'))}",
                f"智能制造能力成熟度：{cmm}",
                "建设总投资、建设起始日期、主要集成商：[待补充/核验]",
                "",
                "## 三、智能工厂建设情况",
                "",
                "围绕工厂建设、研发设计、生产作业、生产管理和运营管理五个环节，企业已登记覆盖情况。各环节具体系统、装备、数据流及业务闭环：[待补充/核验]。",
                "",
                "## 四、建设成效",
                "",
                f"企业档案登记的人工智能技术应用场景比例为 {ai_ratio}。生产效率、不良率、设备利用率、能耗和交付周期等基准值、改善值及佐证材料：[待补充/核验]。",
                "",
                "## 五、后续提升计划",
                "",
                "后续改造目标、里程碑、预算、责任部门和量化验收指标：[待补充/核验]。",
                "",
                "## 六、真实性和保密检查",
                "",
                "- [ ] 所有数字已与审计、财务及生产系统核对",
                "- [ ] 已完成国家秘密、商业秘密和个人信息检查",
                "- [ ] 已由业务、财务、技术和法务负责人复核",
            ]
        )

    @staticmethod
    def _little_giant(company: CompanyProfile) -> str:
        facts = company.facts
        year = facts.get("financials", {}).get("2025", {})
        return "\n".join(
            [
                "# 专精特新“小巨人”企业申请信息初稿",
                "",
                "> 本初稿不代表当期仍可申报；须先检查申报窗口。未知信息不会自动补写。",
                "",
                "## 企业与专业化情况",
                "",
                f"企业名称：{company.name}",
                f"主导产品：{display(get_fact(facts, 'business.main_product'))}",
                f"深耕细分市场时间：{display(get_fact(facts, 'business.specific_market_years'), '年')}",
                "细分市场边界、规模和数据来源：[待补充/核验]",
                "",
                "## 2025年度核心数据（万元）",
                "",
                f"- 营业收入：{display(year.get('revenue'))}",
                f"- 主营业务收入：{display(year.get('main_business_revenue'))}",
                f"- 研发费用：{display(year.get('rd_expense'))}",
                f"- 资产负债率：{display(year.get('debt_ratio'), '%')}",
                "",
                "## 创新与产业链",
                "",
                f"I类知识产权数量：{display(get_fact(facts, 'innovation.type_i_ip_count'), '项')}",
                "知识产权与主导产品对应关系、实际应用及经济效益：[待补充/核验]",
                "产业链关键作用及补短板说明：[待补充/核验]",
                "",
                "## 人工复核清单",
                "",
                "- [ ] 线上和纸质数据完全一致",
                "- [ ] 财务数据与已赋码审计报告一致",
                "- [ ] 市场占有率推导可追溯且不使用虚假第三方证明",
                "- [ ] 材料无涉密信息并完成法定代表人确认",
            ]
        )
