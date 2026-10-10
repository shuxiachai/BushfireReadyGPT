"""Current request metadata without changing pinned historical evidence helpers."""

from src.model_evidence import EvidencePrompt as HistoricalEvidencePrompt

SECTION_PROSE_OUTPUT_CONTRACT = "section-prose-v1"
OUTPUT_CONTRACTS = frozenset({"markdown", SECTION_PROSE_OUTPUT_CONTRACT})


class EvidencePrompt(HistoricalEvidencePrompt):
    """Keep inherited evidence semantics and add an explicit current output mode."""

    def __new__(cls, value, *, assembly=None, request_kind="initial", output_contract=None):
        instance = super().__new__(cls, value, assembly=assembly, request_kind=request_kind)
        contract = getattr(value, "output_contract", "markdown") if output_contract is None else output_contract
        if not isinstance(contract, str) or contract not in OUTPUT_CONTRACTS:
            raise ValueError("Unsupported model output contract.")
        instance.output_contract = contract
        return instance


def protocol_retry_prompt(original_prompt, suffix):
    return EvidencePrompt(
        str(original_prompt) + suffix,
        assembly=getattr(original_prompt, "assembly", None),
        request_kind="protocol_retry",
        output_contract=getattr(original_prompt, "output_contract", "markdown"),
    )
