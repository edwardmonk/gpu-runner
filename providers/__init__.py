from .lambda_labs import LambdaProvider
from .vast_ai import VastProvider

PROVIDERS = {
    "lambda": LambdaProvider,
    "vast": VastProvider,
}
