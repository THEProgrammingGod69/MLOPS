"""Deploy the whole stack to a free Hugging Face Docker Space, then wait until it answers.

One-time setup: create a token with write access at https://huggingface.co/settings/tokens
and run ``hf auth login`` (or set ``HF_TOKEN``). Then, from the repository root:

    python deploy/huggingface/deploy.py [--space NAME] [--no-wait]

Uploads only what the image needs, in a single commit, so each deploy is one build.
"""
import argparse
import os
import sys
import time
import urllib.request

from huggingface_hub import CommitOperationAdd, CommitOperationDelete, HfApi

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
INCLUDE_DIRS = ["configs", "src", "reports", "scripts", "deploy/vercel", "monitoring", "frontend"]
INCLUDE_FILES = ["requirements-api.txt", ".dockerignore", "models/README.md", "models/baseline/xgb_pipeline.pkl",
                 "models/mitigated/xgb_threshold_optimizer_gender.pkl"]
SKIP_PARTS = {"node_modules", "dist", "__pycache__", ".pytest_cache"}
SKIP_SUFFIXES = (".png", ".pyc")
TERMINAL = {"RUNNING", "BUILD_ERROR", "RUNTIME_ERROR", "CONFIG_ERROR", "NO_APP_FILE", "PAUSED", "STOPPED"}


def files_to_upload():
    selected = {"Dockerfile": os.path.join(ROOT, "deploy", "huggingface", "Dockerfile"),
                "README.md": os.path.join(ROOT, "deploy", "huggingface", "README.md")}
    for name in INCLUDE_FILES:
        selected[name] = os.path.join(ROOT, name)
    for folder in INCLUDE_DIRS:
        for directory, subdirs, names in os.walk(os.path.join(ROOT, folder)):
            subdirs[:] = [d for d in subdirs if d not in SKIP_PARTS]
            for name in names:
                if not name.endswith(SKIP_SUFFIXES):
                    path = os.path.join(directory, name)
                    selected[os.path.relpath(path, ROOT).replace(os.sep, "/")] = path
    missing = [k for k, v in selected.items() if not os.path.exists(v)]
    if missing:
        raise SystemExit(f"Missing files: {missing}")
    return selected


def wait_for_space(api, repo_id, url, timeout=2400):
    started, last = time.time(), None
    while time.time() - started < timeout:
        stage = api.get_space_runtime(repo_id).stage
        if stage != last:
            print(f"[{time.time() - started:5.0f}s] {stage}", flush=True)
            last = stage
        if stage in TERMINAL:
            break
        time.sleep(15)
    if last != "RUNNING":
        print(f"Space did not reach RUNNING ({last}). Logs: https://huggingface.co/spaces/{repo_id}?logs=build")
        return False
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"{url}/api/v1/health", timeout=30) as response:
                if response.status == 200:
                    print("API healthy", flush=True)
                    return True
        except Exception:
            pass
        time.sleep(5)
    print("Space is RUNNING but the API did not answer yet")
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--space", default="student-dropout-ews")
    parser.add_argument("--no-wait", action="store_true")
    args = parser.parse_args()

    api = HfApi()
    user = api.whoami()["name"]
    repo_id = f"{user}/{args.space}"
    url = f"https://{repo_id.replace('/', '-').replace('_', '-').lower()}.hf.space"

    api.create_repo(repo_id, repo_type="space", space_sdk="docker", private=False, exist_ok=True)
    selected = files_to_upload()
    existing = set(api.list_repo_files(repo_id, repo_type="space"))
    operations = [CommitOperationAdd(path_in_repo=k, path_or_fileobj=v) for k, v in sorted(selected.items())]
    operations += [CommitOperationDelete(path_in_repo=p) for p in sorted(existing - set(selected) - {".gitattributes"})]
    commit = api.create_commit(repo_id, repo_type="space", operations=operations,
                               commit_message="Deploy student dropout early warning stack")
    print(f"Uploaded {len(selected)} files to https://huggingface.co/spaces/{repo_id} ({commit.oid[:8]})")
    print(f"App URL: {url}/ui/")
    if args.no_wait:
        return 0
    return 0 if wait_for_space(api, repo_id, url) else 1


if __name__ == "__main__":
    sys.exit(main())
