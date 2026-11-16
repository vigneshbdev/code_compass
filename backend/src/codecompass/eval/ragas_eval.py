"""RAGAS faithfulness for eval answers (FR-042, research R11, task T147).

Imported only by `make eval`; RAGAS lives in the `eval` dependency group, not the app image.
"""

from __future__ import annotations

import logging

from langchain_core.language_models import BaseChatModel

from codecompass.eval.metrics import QuestionResult

logger = logging.getLogger(__name__)


async def score_faithfulness(results: list[QuestionResult], judge: BaseChatModel) -> None:
    """Fill `faithfulness` for answers that make claims; leaves None when scoring fails."""
    from ragas import SingleTurnSample
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import Faithfulness

    metric = Faithfulness(llm=LangchainLLMWrapper(judge))
    for result in results:
        if result.status not in {"complete", "unverified"} or not result.contexts:
            continue
        sample = SingleTurnSample(
            user_input=result.question,
            response=result.answer,
            retrieved_contexts=result.contexts,
        )
        try:
            result.faithfulness = round(float(await metric.single_turn_ascore(sample)), 3)
        except Exception:
            logger.warning("faithfulness scoring failed for %s", result.id, exc_info=True)
