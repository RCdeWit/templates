import argparse
import os
import subprocess
import tempfile
import yaml
from pathlib import Path


def _read_yaml_file(file_path):
    with open(file_path, "r") as stream:
        return yaml.safe_load(stream)


def _get_lora_storage_uri() -> str:
    artifact_storage = os.environ.get("ANYSCALE_CLOUD_STORAGE_BUCKET")
    artifact_storage = artifact_storage.rstrp("/")
    return f"{artifact_storage}/fine_tuning/"


def main():
    # Set up the argument parser
    parser = argparse.ArgumentParser(
        description="Submit a job with configuration files"
    )
    parser.add_argument(
        "job_config", type=str, help="Path to the job configuration YAML file"
    )
    parser.add_argument(
        "finetune_config",
        type=str,
        help="Path to the fine-tuning configuration YAML file",
    )

    # Parse arguments
    args = parser.parse_args()

    job_config_path = args.job_config
    finetune_config_path = args.finetune_config

    job_config = _read_yaml_file(job_config_path)
    training_config = _read_yaml_file(finetune_config_path)

    is_lora = "lora_config" in training_config
    if is_lora:
        storage_uri = _get_lora_storage_uri()
        entrypoint = f"llmforge dev finetune {finetune_config_path} --forward-best-checkpoint-remote-uri={storage_uri}"
        print(f"Note: Lora weights will also be stored under {storage_uri} to allow multi serving.")
    else:
        entrypoint = f"llmforge dev finetune {finetune_config_path}"

    job_config["entrypoint"] = entrypoint
    job_config["name"] = Path(finetune_config_path).stem

    api_key = os.environ.get("WANDB_API_KEY")
    if api_key:
        job_config.setdefault("runtime_env", {}).setdefault("env_vars", {})[
            "WANDB_API_KEY"
        ] = api_key

    with tempfile.NamedTemporaryFile(
        mode="w+", delete=False, dir=".", suffix=".yaml"
    ) as temp_file:
        yaml.safe_dump(job_config, temp_file)
        temp_file_name = temp_file.name

    # Call `anyscale job submit` on the temporary YAML file
    try:
        subprocess.run(["anyscale", "job", "submit", temp_file_name], check=True)
    finally:
        # Clean up by deleting the temporary file
        os.remove(temp_file_name)


if __name__ == "__main__":
    main()
