# 任务7.7首次真实排序运行失效说明

- 运行日期：2026-07-21
- 产物：`reports/retrieval_ranking_real_v1_invalid_vector_port_20260721.json`
- SHA-256：`e2396f97ca5f5f6e89c2bfb9c6e53a5e9ec064ce2135371c928a4028836acd5c`
- 判定：无效，不得用于候选晋级或生产决策。

## 观察结果

40题的向量阶段全部失败，关键词扫描和Reranker各完成40次。Reranker登记246713输入Token，按每百万Token 0.8元估算为0.1973704元。无效报告的总估算0.20761元还包含40次Embedding的保守预算预留0.01024元，但向量错误发生在调用远程Embedding之前，因此该预留不代表实际Embedding调用或账单。

## 原因与修复

执行入口把只有`similarity_search`的只读Chroma对象直接交给要求`search`方法的共享评估适配器。Mock搜索对象恰好实现了`search`，原测试只验证算法调用次数，没有验证真实工厂的接口形状。

修复后由`CurrentChromaKnowledgeSearchAdapter`包装只读对象再注入稳定Port；新增真实工厂形状测试，并要求40题向量阶段全部失败时拒绝发布正式报告。恢复计划绑定本文件对应的无效JSON哈希，必须重新预检和重新取得费用确认后才可再次调用真实服务。
