"""Model information and pricing for Bedrock Claude models."""

from typing import Dict, NamedTuple


class ModelInfo(NamedTuple):
    """Information about a Bedrock model."""
    name: str
    provider: str
    input_price: float  # per million tokens
    output_price: float  # per million tokens
    context_window: int
    description: str
    region: str = "us-east-1"


# Model pricing and information
# Source: https://aws.amazon.com/bedrock/pricing/
BEDROCK_MODELS: Dict[str, ModelInfo] = {
    # Haiku models (cheapest)
    "us.anthropic.claude-3-haiku-20240307-v1:0": ModelInfo(
        name="Claude 3 Haiku",
        provider="Anthropic via AWS Bedrock",
        input_price=0.25,
        output_price=1.25,
        context_window=200_000,
        description="Fast, cost-effective model for simple queries",
        region="us-east-1"
    ),
    "anthropic.claude-3-haiku-20240307-v1:0": ModelInfo(
        name="Claude 3 Haiku",
        provider="Anthropic via AWS Bedrock",
        input_price=0.25,
        output_price=1.25,
        context_window=200_000,
        description="Fast, cost-effective model for simple queries",
        region="us-east-1"
    ),
    "us.anthropic.claude-haiku-4-5-20251001-v1:0": ModelInfo(
        name="Claude Haiku 4.5",
        provider="Anthropic via AWS Bedrock",
        input_price=0.25,
        output_price=1.25,
        context_window=200_000,
        description="Latest Haiku - fastest and most cost-effective",
        region="us-east-1"
    ),
    "anthropic.claude-haiku-4-5-20251001-v1:0": ModelInfo(
        name="Claude Haiku 4.5",
        provider="Anthropic via AWS Bedrock",
        input_price=0.25,
        output_price=1.25,
        context_window=200_000,
        description="Latest Haiku - fastest and most cost-effective",
        region="us-east-1"
    ),

    # Sonnet models (balanced)
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0": ModelInfo(
        name="Claude Sonnet 4.5",
        provider="Anthropic via AWS Bedrock",
        input_price=3.0,
        output_price=15.0,
        context_window=200_000,
        description="Latest Sonnet - best intelligence and coding",
        region="us-east-1"
    ),
    "anthropic.claude-sonnet-4-5-20250929-v1:0": ModelInfo(
        name="Claude Sonnet 4.5",
        provider="Anthropic via AWS Bedrock",
        input_price=3.0,
        output_price=15.0,
        context_window=200_000,
        description="Latest Sonnet - best intelligence and coding",
        region="us-east-1"
    ),
    "us.anthropic.claude-sonnet-4-20250514-v1:0": ModelInfo(
        name="Claude Sonnet 4",
        provider="Anthropic via AWS Bedrock",
        input_price=3.0,
        output_price=15.0,
        context_window=200_000,
        description="Claude Sonnet 4",
        region="us-east-1"
    ),
    "anthropic.claude-sonnet-4-20250514-v1:0": ModelInfo(
        name="Claude Sonnet 4",
        provider="Anthropic via AWS Bedrock",
        input_price=3.0,
        output_price=15.0,
        context_window=200_000,
        description="Claude Sonnet 4",
        region="us-east-1"
    ),
    "anthropic.claude-3-5-sonnet-20241022-v2:0": ModelInfo(
        name="Claude 3.5 Sonnet v2",
        provider="Anthropic via AWS Bedrock",
        input_price=3.0,
        output_price=15.0,
        context_window=200_000,
        description="Best balance of intelligence and cost",
        region="us-east-1"
    ),
    "us.anthropic.claude-3-5-sonnet-20240620-v1:0": ModelInfo(
        name="Claude 3.5 Sonnet v1",
        provider="Anthropic via AWS Bedrock",
        input_price=3.0,
        output_price=15.0,
        context_window=200_000,
        description="Previous Sonnet version",
        region="us-east-1"
    ),
    "anthropic.claude-3-5-sonnet-20240620-v1:0": ModelInfo(
        name="Claude 3.5 Sonnet v1",
        provider="Anthropic via AWS Bedrock",
        input_price=3.0,
        output_price=15.0,
        context_window=200_000,
        description="Previous Sonnet version",
        region="us-east-1"
    ),

    # Opus models (highest quality)
    "us.anthropic.claude-opus-4-1-20250805-v1:0": ModelInfo(
        name="Claude Opus 4.1",
        provider="Anthropic via AWS Bedrock",
        input_price=15.0,
        output_price=75.0,
        context_window=200_000,
        description="Highest quality model",
        region="us-east-1"
    ),
    "anthropic.claude-opus-4-1-20250805-v1:0": ModelInfo(
        name="Claude Opus 4.1",
        provider="Anthropic via AWS Bedrock",
        input_price=15.0,
        output_price=75.0,
        context_window=200_000,
        description="Highest quality model",
        region="us-east-1"
    ),

    # EU region models
    "eu.anthropic.claude-3-5-sonnet-20241022-v2:0": ModelInfo(
        name="Claude 3.5 Sonnet v2 (EU)",
        provider="Anthropic via AWS Bedrock",
        input_price=3.0,
        output_price=15.0,
        context_window=200_000,
        description="EU Frankfurt region deployment",
        region="eu-central-1"
    ),
}


def get_model_info(model_id: str) -> ModelInfo:
    """
    Get model information and pricing.

    Args:
        model_id: Bedrock model ID or inference profile ID

    Returns:
        ModelInfo object with pricing and details

    Raises:
        KeyError: If model is not found
    """
    return BEDROCK_MODELS.get(model_id, ModelInfo(
        name="Unknown Model",
        provider="Anthropic via AWS Bedrock",
        input_price=3.0,  # Default to Sonnet pricing
        output_price=15.0,
        context_window=200_000,
        description="Unknown model - using estimated pricing",
        region="us-east-1"
    ))


def estimate_cost(input_tokens: int, output_tokens: int, model_id: str) -> float:
    """
    Estimate cost for a query.

    Args:
        input_tokens: Estimated input tokens
        output_tokens: Estimated output tokens
        model_id: Bedrock model ID

    Returns:
        Estimated cost in USD
    """
    info = get_model_info(model_id)
    input_cost = (input_tokens / 1_000_000) * info.input_price
    output_cost = (output_tokens / 1_000_000) * info.output_price
    return input_cost + output_cost


def format_price(price: float) -> str:
    """Format price for display."""
    if price < 0.01:
        return f"${price:.4f}"
    elif price < 1:
        return f"${price:.3f}"
    else:
        return f"${price:.2f}"