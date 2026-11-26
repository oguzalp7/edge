"""Submodule: constants."""

import re


_AUDIT_EXTS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".py"}


_JS_TS_EXTS = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}


_USE_SERVER_DIRECTIVE_RE = re.compile(r'^\s*["\']use server["\']\s*;?\s*$', re.MULTILINE)


_IGNORED_DIRS = {".git", "node_modules", ".next", "dist", "build", ".edge", "__pycache__", "tests", "__tests__"}


_VALID_VERDICTS = {"confirmed", "needs_validation", "rejected"}


_VALID_SEVERITIES = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}


_VALID_LEDGER_STATUSES = {"covered", "planned", "out_of_scope"}


_PRIV_BYPASS_RE = re.compile(r"\b(system-caller|bypassAuth|skipAuth)\b")


_ABAC_SINK_RE = re.compile(r"\b(db\.(?:insert|update|delete)|[A-Za-z0-9_]*Repository\.[A-Za-z0-9_]+|\.upsert\s*\()")


_ABAC_GUARD_RE = re.compile(
    r"\b(?:requireAuth|getCurrentSessionAction|assert[A-Za-z0-9_]*Access|evaluate[A-Za-z0-9_]*Access|getSession|checkPermission|getServerSession|auth)\s*\("
)


_TOKEN_GUARD_RE = re.compile(
    r"\b(?:hashInvitationToken|verify[A-Za-z0-9_]*Token|validate[A-Za-z0-9_]*Token|timingSafeEqual)\s*\("
)


_POLICY_AUTH_FIELD_RE = re.compile(r"\b(?:minAuthLevel|authLevel|requireAuth)\b")


_RUN_ACTION_CALL_RE = re.compile(r"\b(runAction|executeAction)\b")


_READ_ONLY_REPO_METHOD_RE = re.compile(
    r"^[A-Za-z0-9_]*Repository\.(?:find|list|get|search|lookup|count|exists|validate)[A-Za-z0-9_]*$"
)


_DATA_MUTATION_RE = re.compile(r"\bdb\.(update|delete)\s*\(")


_SQL_RAW_INTERP_RE = re.compile(r"sql\.raw\s*\([^)]*\$\{")


_DANGEROUS_HTML_RE = re.compile(r"\bdangerouslySetInnerHTML\b")


_HTML_SANITIZER_RE = re.compile(r"\b(?:DOMPurify|sanitize[A-Za-z0-9_]*)\b")


_CMD_EXEC_RE = re.compile(r"(?:\bchild_process\.exec\s*\(|\bexecSync\s*\(|\bos\.system\s*\(|\bsubprocess\.run\s*\([^)]*shell\s*=\s*True)")


_PY_CMD_EXEC_RE = re.compile(r"(?:\bos\.system\s*\(|\bsubprocess\.run\s*\([^)]*shell\s*=\s*True)")


_EVAL_SINK_RE = re.compile(r"(?:\beval\s*\(|\bnew\s+Function\s*\()")


_PY_EVAL_SINK_RE = re.compile(r"\beval\s*\(")


_MATH_RANDOM_RE = re.compile(r"\bMath\.random\s*\(")


_SEC_CTX_RE = re.compile(r"\b(?:token|secret|otp|password|key|salt|nonce|session|auth)\b", re.IGNORECASE)


_HARDCODED_SECRET_RE = re.compile(r"(?:sk_live_[A-Za-z0-9_]+|ghp_[A-Za-z0-9]{10,}|AKIA[0-9A-Z]{16})")


_FN_START_RE = re.compile(
    r"^(?:export\s+(?:default\s+)?)?(?:async\s+)?(?:function\s*\*?\s*([A-Za-z0-9_$]+)|(?:const|let|var)\s+([A-Za-z0-9_$]+)\s*(?::[^=]+)?=\s*(?:async\s*)?(?:<[^>]*>\s*)?\()"
)


_PY_FN_START_RE = re.compile(r"^(?:async\s+)?def\s+([A-Za-z0-9_]+)\s*\(")


_POLICY_OBJ_START_RE = re.compile(r"^(?:export\s+)?const\s+([A-Za-z0-9_$]+)\s*=\s*\{")


_POLICY_KEY_START_RE = re.compile(r"^\s*([A-Za-z0-9_$]+)\s*:\s*\{")


_EXPORT_SPEC_RE = re.compile(r"\bexport\s+(?:type\s+)?\{([^}]*)\}")
