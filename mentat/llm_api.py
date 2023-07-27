import logging
import os
import sys
from dataclasses import dataclass
from typing import Generator

import openai
import tiktoken
from dotenv import load_dotenv
from termcolor import cprint

from .config_manager import mentat_dir_path, user_config_file_name

package_name = __name__.split(".")[0]


# Check for .env file or already exported API key
# If no api key found, exit and warn user
def setup_api_key():
    if not load_dotenv(os.path.join(mentat_dir_path, ".env")):
        load_dotenv()
    key = os.getenv("OPENAI_API_KEY")
    try:
        openai.api_key = key
        openai.Model.list()  # Test the API key
    except openai.error.AuthenticationError:
        cprint(
            (
                "No valid OpenAI api key detected.\nEither place your key into a .env"
                " file or export it as an environment variable."
            ),
            "red",
        )
        sys.exit(0)


async def call_llm_api(messages: list[dict[str, str]], model) -> Generator:
    if (
        "PYTEST_CURRENT_TEST" in os.environ
        and "--benchmark" not in sys.argv
        and os.getenv("MENTAT_BENCHMARKS_RUNNING") == "false"
    ):
        logging.critical("OpenAI call made in non benchmark test environment!")
        sys.exit(1)

    response = await openai.ChatCompletion.acreate(
        model=model,
        messages=messages,
        temperature=0.5,
        stream=True,
    )

    return response


def count_tokens(message: str) -> int:
    return len(tiktoken.encoding_for_model("gpt-4").encode(message))


# Remove version from end of model name - Version does not affect pricing
def shorten(model: str) -> str:
    # Remove the part that starts with '-' and ends with only numbers
    model_short = re.sub('-\d+$', '', model)
    return model_short


def choose_model(messages: list[dict[str, str]], allow_32k) -> str:
    prompt_token_count = 0
    tokenizer = tiktoken.encoding_for_model("gpt-4")
    for message in messages:
        encoding = tokenizer.encode(message["content"])
        prompt_token_count += len(encoding)
    cprint(f"\nTotal token count: {prompt_token_count}", "cyan")

    model = "gpt-4-0314"
    token_buffer = 500
    if prompt_token_count > 8192 - token_buffer:
        if allow_32k:
            model = "gpt-4-32k-0314"
            if prompt_token_count > 32768 - token_buffer:
                cprint(
                    "Warning: gpt-4-32k-0314 has a token limit of 32768. Attempting"
                    " to run anyway:"
                )
        else:
            cprint(
                (
                    "Warning: gpt-4-0314 has a maximum context length of 8192 tokens."
                    " If you have access to gpt-4-32k-0314, set allow-32k to `true` in"
                    f" `{os.path.join(mentat_dir_path, user_config_file_name)}` to use"
                    " it. Attempting to run with gpt-4-0314:"
                ),
                "yellow",
            )
    return model, prompt_token_count


@dataclass
class CostTracker:
    total_cost: int = 0

    def display_api_call_stats(
        self,
        num_prompt_tokens: int,
        num_sampled_tokens: int,
        model: str,
        call_time: float,
    ) -> None:
        cost_per_1000_tokens = {
            'gpt-3.5-turbo': (0.0015, 0.002),
            'gpt-3.5-turbo-16K': (0.003, 0.004),
            'gpt-4': (0.03, 0.06),
            'gpt-4-32K': (0.06, 0.12)
        }

        model_short = shorten(model) 
        if (model_short not in cost_per_1000_tokens):
            cprint("Warning: No price set for model " + model + " (shortened: " + model_short + ")")

        prompt_cost = (num_prompt_tokens / 1000) * cost_per_1000_tokens[model_short][0]
        sampled_cost = (num_sampled_tokens / 1000) * cost_per_1000_tokens[model_short][1]

        tokens_per_second = num_sampled_tokens / call_time
        call_cost = prompt_cost + sampled_cost

        speed_and_cost_string = (
            f"Speed: {tokens_per_second:.2f} tkns/s | Cost: ${call_cost:.2f}"
        )
        cprint(speed_and_cost_string, "cyan")

        costs_logger = logging.getLogger("costs")
        costs_logger.info(speed_and_cost_string)

        self.total_cost += call_cost

    def display_total_cost(self) -> None:
        cprint(f"\nTotal session cost: ${self.total_cost:.2f}", color="light_blue")