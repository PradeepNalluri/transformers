import gzip
import multiprocessing
import os
import shutil
import time

import numpy as np
from datasets import load_dataset


def get_hash(example):
    """Get hash of content field."""
    return {"hash": hash(example["content"])}


def line_stats(example):
    """Calculates mean and max line length of file."""
    line_lengths = [len(line) for line in example["content"].splitlines()]
    return {"line_mean": np.mean(line_lengths), "line_max": max(line_lengths)}


def alpha_stats(example):
    """Calculates mean and max line length of file."""
    alpha_frac = np.mean([c.isalnum() for c in example["content"]])
    return {"alpha_frac": alpha_frac}


def check_uniques(example, uniques):
    """Check if current hash is still in set of unique hashes and remove if true."""
    if example["hash"] in uniques:
        uniques.remove(example["hash"])
        return True
    else:
        return False


def is_autogenerated(example):
    """Check if file is autogenerated by looking for keywords in the first few lines of the file."""
    keywords = ["auto-generated", "autogenerated", "automatically generated"]
    scan_width = 5
    lines = example["content"].splitlines()
    for _, line in zip(range(scan_width), lines):
        for keyword in keywords:
            if keyword in line.lower():
                return {"autogenerated": True}
    else:
        return {"autogenerated": False}


def preprocess(example):
    """Chain all preprocessing steps into one function to not fill cache."""
    results = dict()
    results.update(get_hash(example))
    results.update(line_stats(example))
    results.update(alpha_stats(example))
    results.update(is_autogenerated(example))
    return results


def filter(example, uniques):
    """Filter dataset with heuristics."""
    if not check_uniques(example, uniques):
        return False
    elif example["autogenerated"]:
        return False
    elif example["line_max"] > 1000:
        return False
    elif example["line_mean"] > 100:
        return False
    elif example["alpha_frac"] < 0.25:
        return False
    else:
        return True


def compress_file(file_path):
    """Compress a file with g-zip."""
    with open(file_path, "rb") as f_in:
        with gzip.open(file_path + ".gz", "wb", compresslevel=6) as f_out:
            shutil.copyfileobj(f_in, f_out)
    os.unlink(file_path)


# Settings
N_CPUS = multiprocessing.cpu_count()
print(f"Number of CPUs: {N_CPUS}")
dataset_name = "codeparrot"
output_dir = "codeparrot-clean"
hash_dir = "codeparrot-hash"
samples_per_file = 100_000

# Load dataset
t_start = time.time()
ds = load_dataset(dataset_name, split="train")
print(f"Time to load dataset: {time.time()-t_start:.2f}")

# Run preprocessing
t_start = time.time()
ds = ds.map(preprocess, num_proc=N_CPUS)
print(f"Time to preprocess dataset: {time.time()-t_start:.2f}")

# Save hashes for analysis
if not os.path.exists(hash_dir):
    os.makedirs(hash_dir)
ds.remove_columns(["content"]).to_json(hash_dir + "/data_hash.json")

# Deduplicate hashes
uniques = set(ds.unique("hash"))
frac = len(uniques) / len(ds)
print(f"Fraction of duplicates: {1-frac:.2%}")

# Deduplicate data and apply heuristics
t_start = time.time()
ds_filter = ds.filter(filter, fn_kwargs={"uniques": uniques})
print(f"Time to filter dataset: {time.time()-t_start:.2f}")
print(f"Size of filtered dataset: {len(ds_filter)}")

# Save data in batches of samples_per_file
if not os.path.exists(output_dir):
    os.makedirs(output_dir)
t_start = time.time()
for file_number, index in enumerate(range(0, len(ds_filter), samples_per_file)):
    file_path = f"{output_dir}/file-{file_number+1:012}.json"
    end_index = min(len(ds_filter), index + samples_per_file)
    ds_filter.select(list(range(index, end_index))).to_json(file_path)
    compress_file(file_path)
print(f"Time to save dataset: {time.time()-t_start:.2f}")
