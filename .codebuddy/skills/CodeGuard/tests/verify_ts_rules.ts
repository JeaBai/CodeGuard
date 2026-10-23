/**
 * CodeGuard P2-4: TypeScript 规则验证测试集
 * 用于验证 GOLD_NO_ANY_TYPE 规则
 */

// === TP 样本（应触发规则） ===

function processData(input: any): any {  // [违规] any 类型退化
    return input.data;
}

const config: any = { timeout: 5000 };  // [违规] any 类型

interface Handler {
    callback: any;  // [违规] 应使用具体类型
}

// === TN 样本（不应触发规则） ===

function safeProcess(input: Record<string, unknown>): unknown {  // ✅ OK: unknown + 具体类型
    return (input as { data: number }).data;
}

interface SafeConfig {
    timeout: number;     // ✅ OK
    retries?: number;    // ✅ OK: optional
}

type Result<T> = {        // ✅ OK: 泛型
    data: T;
    error?: string;
};

export { processData, config, Handler, safeProcess, SafeConfig, Result };
