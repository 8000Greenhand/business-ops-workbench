# 城市运力经营工作台 V2 产品规格

## 1. 目标

V2 不追求增加更多图表，而是把现有“城市运力经营”页面从经营展示升级为可解释的运力诊断工作台。

核心链路：

> 需求变化 → 司机供给 → 有效在线 → 接单/完单 → 单位运力效率 → 成本/毛利 → 异常定位 → 运营动作

所有数据仍为模拟经营数据，仅用于经营分析能力演示，不代表任何平台内部真实指标、阈值或经营规则。

## 2. 设计来源

V2 由三类输入共同形成：

1. **现有代码能力**
   - 等长周期比较
   - 城市 / 区域 / 时段下钻
   - GMV 与完成订单量拆解
   - 运力缺口、低效运力、毛利风险规则
   - P0 / P1 / P2 异常池
   - 配置化诊断阈值

2. **公开项目启发**
   - ride-hailing operations dashboard：运营控制台、区域热区、司机供给不足预警
   - NYC rideshare forecasting：城市 → 区域 → 时间 → 趋势 → 单区域下钻
   - urban mobility logistics：供需失衡 → 调度动作
   - taxi operations dashboard：平台视角与司机效率视角

3. **模拟经营设计**
   - 司机供给漏斗
   - 有效运力率
   - 单司机效率
   - 供需缺口分型
   - 补贴效率与毛利约束

## 3. V2 核心经营问题

V2 必须优先回答以下问题：

1. 当前经营结果变好或变差，主要来自需求、履约、客单价还是运力效率？
2. 哪个城市、区域、时段存在供需失衡？
3. 供给不足究竟是司机数量不足、在线不足、有效在线不足，还是接单/履约异常？
4. 当前在线供给是否真正转化为订单和 GMV？
5. 司机人效是否恶化？
6. 补贴增长是否带来了有效增量，还是只拉高成本？
7. 哪些异常需要今天优先处理？
8. 每条异常对应的下一步运营动作是什么？

## 4. 页面结构

V2 继续保持单页主工作台，不拆成大量导航页。

### A. 筛选与周期
- 当前周期起始日
- 当前周期结束日
- 城市
- 区域（选择单城市后启用）
- 时段
- 自动生成上一等长周期

### B. 核心经营结果
首屏只放 6 个一级指标：
- GMV
- 完单率
- 毛利率
- 司机供给人次
- 有效在线时长
- GMV / 有效在线小时

目的：同时回答规模、履约、运力和利润约束。

### C. 今日经营异常池
优先展示 P0 / P1 / P2：
- 定位路径
- 问题类型
- 关键证据
- 经营判断
- 建议动作

异常优先于趋势图展示。

### D. 经营结果拆解
保留：
- GMV = 完成订单量 × 客单价
- 完成订单量 = 需求订单量 × 完单率

新增：
- 有效在线小时 = 在线时长 × 有效在线率
- 单位运力产出 = GMV / 有效在线小时

### E. 供需诊断
按 city × zone × time_bucket 展示：
- 需求订单
- 活跃司机
- 在线司机
- 有效在线司机
- 在线时长
- 有效在线时长
- 完单率
- 供需强度
- GMV / 有效在线小时
- 诊断标签

### F. 司机经营
新增司机供给经营区：
- 司机供给人次
- 在线司机人次
- 有效在线司机人次
- 每供给人次在线时长
- 每供给人次完单
- 每供给人次 GMV
- 完单 / 有效在线小时
- GMV / 有效在线小时
- 有效在线率

### G. 城市 / 区域经营对比
继续保留城市和区域对比，但新增供给指标与效率指标。

### H. 核心趋势
趋势图只保留决策价值高的：
- GMV
- 完单率
- 活跃司机
- 有效在线时长
- GMV / 有效在线小时
- 毛利率

## 5. V2 数据模型

### 5.1 粒度

继续使用：

> date × city × zone × time_bucket

V2 暂不引入 driver_id 级事实表。司机指标为同粒度下的聚合模拟事实。

### 5.2 现有原子指标

保留：
- demand_orders
- completed_orders
- gmv
- online_hours
- platform_revenue
- driver_subsidy
- other_variable_cost

### 5.3 新增原子指标

第一阶段新增：
- active_drivers：该 date × city × zone × time_bucket 粒度的司机供给人次
- online_drivers：该粒度产生在线行为的司机人次
- effective_online_drivers：满足有效在线条件的司机人次
- effective_online_hours：可用于承接订单的有效在线时长

> 重要口径：V2 第一阶段没有 driver_id，因此以上三个字段在跨日或跨时段聚合后代表“司机人次”，不能解释为唯一司机数。唯一活跃司机、留存和召回必须等 driver_id 级数据后再做。

约束：
- effective_online_drivers <= online_drivers <= active_drivers
- effective_online_hours <= online_hours
- 所有指标 >= 0
- 缺失不得静默补 0

### 5.4 新增派生指标

- effective_online_rate = effective_online_hours / online_hours
- drivers_effective_rate = effective_online_drivers / online_drivers
- demand_per_effective_driver = demand_orders / effective_online_drivers
- orders_per_active_driver = completed_orders / active_drivers（每供给人次完单）
- gmv_per_active_driver = gmv / active_drivers（每供给人次 GMV）
- online_hours_per_active_driver = online_hours / active_drivers（每供给人次在线时长）
- gmv_per_effective_online_hour = gmv / effective_online_hours
- orders_per_effective_online_hour = completed_orders / effective_online_hours

所有比率必须聚合原子分子、分母后重新计算，禁止简单平均。

## 6. 供需诊断规则 V2

V2 诊断不依赖单指标。

### 6.1 需求突增
条件信号：
- demand_orders 明显增长
- 供给指标尚未同步恶化

含义：需求侧变化，需要继续观察供给承接能力。

### 6.2 运力不足
组合信号：
- demand_orders 增长
- effective_online_hours 增长明显落后于需求
- completion_rate 下降

### 6.3 在线不足
组合信号：
- active_drivers 尚可
- online_hours / active_driver 下降
- completion_rate 下降

### 6.4 有效运力不足
组合信号：
- online_hours 不低
- effective_online_rate 下降
- completion_rate 下降

### 6.5 履约异常
组合信号：
- 需求与有效运力变化相对稳定
- completion_rate 明显下降

V2 第一阶段数据尚无应答字段，因此不将该问题命名为“应答异常”。

### 6.6 司机效率下降
组合信号：
- active_drivers 或 effective_online_hours 增长
- completed_orders / active_driver 下降
- GMV / effective_online_hour 下降

### 6.7 运力冗余
组合信号：
- effective_online_hours 显著增长
- demand_orders 平稳或下降
- 单位运力产出下降

### 6.8 补贴低效
组合信号：
- subsidy_rate 上升
- completion_rate / GMV 改善不足
- 单位运力产出未改善

### 6.9 毛利风险
继续沿用现有红线与缓冲区规则。

## 7. 异常优先级

### P0
立即处理：
- 严重运力不足且完单率明显恶化
- 毛利触线
- 多个关键效率指标同步恶化

### P1
当日重点处理：
- 有效运力不足
- 运力冗余
- 司机效率显著下降
- 毛利逼近红线
- 补贴低效

### P2
关注：
- 需求突增
- 毛利缓冲明显收窄
- 轻度效率下降

## 8. 下钻路径

统一为：

> 城市 → 区域 → 时段 → 供需 / 司机效率 / 毛利

V2 第一阶段不做 driver_id 级下钻，避免模拟粒度超过数据可信边界。

## 9. 第一阶段实施范围

### 保留
- PeriodWindow
- 等长周期比较
- MetricComparison
- GMV / 订单量 bridge
- city / zone / time_bucket 粒度
- 毛利红线
- 现有 Streamlit 单页
- 异常卡片结构

### 修改
1. simulation/city_supply.py
   - 增加司机与有效在线模拟字段
   - 三个现有场景同步注入新供给信号

2. metrics/city_supply.py
   - 增加新原子字段验证
   - 增加新派生指标
   - 新比率统一使用聚合后重算

3. diagnostics/city_supply.py
   - 保留现有规则
   - 扩展有效运力不足、司机效率下降、运力冗余等判断所需输入

4. ui/city_supply_dashboard.py
   - 将新指标加入 period comparison
   - 增加 driver efficiency comparison
   - 扩充异常证据链

5. ui/pages/8_city_supply_ops.py
   - 第一轮只做必要展示接入
   - 不进行视觉大改版

6. tests/test_city_supply_dashboard.py
   - 增加新指标约束测试
   - 增加聚合后重算测试
   - 增加各诊断场景测试

## 10. 暂不实现

以下内容有价值，但不属于 V2 第一阶段：
- 实时定位
- 地图轨迹
- 司机 ID 明细
- 司机留存 / 召回
- 预测模型
- 天气与活动外部变量
- 动态调度算法
- 实时派单
- 真实平台阈值
- 应答率（缺少模拟原子字段前不伪造）

## 11. 验收标准

V2 第一阶段完成时必须满足：

1. 原有 V1 场景仍可运行。
2. 新增司机供给字段满足逻辑约束。
3. 比率均由聚合后分子 / 分母重新计算。
4. 页面可看到司机供给与有效在线效率。
5. 供需诊断不再只依赖 online_hours。
6. 异常池能区分至少：
   - 运力不足
   - 有效运力不足 / 在线不足
   - 运力冗余或司机效率下降
   - 毛利风险
7. 无真实平台口径暗示。
8. pytest 全部通过后才允许合并回原运力分支。