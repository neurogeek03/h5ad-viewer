#!/usr/bin/env python3
"""
reader.py — reads an .h5ad file and outputs a JSON summary to stdout.
Usage: python reader.py <path_to_file.h5ad>
"""

import sys
import json
import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")


def infer_normalization(matrix, name="X"):
    """
    Infer normalization state of a matrix by sampling up to 1000 rows.
    Returns a dict with 'label' and 'detail'.
    """
    try:
        # Take first 1000 rows (sequential slice works with backed/h5py matrices)
        n = matrix.shape[0]
        slc = slice(0, min(1000, n))

        # Handle sparse matrices — check the chunk, not the parent (e.g. _CSRDataset)
        chunk = matrix[slc]
        if hasattr(chunk, "toarray"):
            sample = chunk.toarray()
        else:
            sample = np.array(chunk)

        sample = sample.astype(float)

        has_negatives = bool(np.any(sample < 0))
        max_val = float(np.max(sample))
        min_val = float(np.min(sample))

        if has_negatives:
            # Check if it looks z-scored (mean ~0, std ~1 per gene) or just log+scaled
            col_means = np.nanmean(sample, axis=0)
            if np.abs(np.mean(col_means)) < 1.0:
                return {"label": "scaled (z-scored)", "detail": f"min={min_val:.2f}, max={max_val:.2f}"}
            else:
                return {"label": "log-normalized + scaled", "detail": f"min={min_val:.2f}, max={max_val:.2f}"}

        # All non-negative from here
        all_integers = bool(np.all(sample == np.floor(sample)))
        if all_integers:
            row_sums = sample.sum(axis=1)
            return {
                "label": "raw counts",
                "detail": f"row sum range: {row_sums.min():.0f}–{row_sums.max():.0f}",
            }

        # Float non-negative
        row_sums = sample.sum(axis=1)
        row_sum_cv = float(np.std(row_sums) / np.mean(row_sums)) if np.mean(row_sums) > 0 else 999

        if row_sum_cv < 0.05:
            return {
                "label": "library-size normalized",
                "detail": f"row sums ≈ {np.mean(row_sums):.0f} (CV={row_sum_cv:.3f})",
            }

        if max_val < 20:
            return {
                "label": "log-normalized",
                "detail": f"max={max_val:.2f}, row sum CV={row_sum_cv:.2f}",
            }

        return {
            "label": "unknown / partially processed",
            "detail": f"min={min_val:.2f}, max={max_val:.2f}",
        }

    except Exception as e:
        return {"label": "unknown", "detail": str(e)}


def summarize_series(series):
    """Return a column summary dict for a pandas Series."""
    dtype_str = str(series.dtype)
    null_count = int(series.isna().sum())
    n = len(series)

    # Numeric
    if pd.api.types.is_numeric_dtype(series):
        non_null = series.dropna()
        return {
            "type": "numeric",
            "dtype": dtype_str,
            "null_count": null_count,
            "min": float(non_null.min()) if len(non_null) else None,
            "max": float(non_null.max()) if len(non_null) else None,
            "mean": float(non_null.mean()) if len(non_null) else None,
        }

    # Categorical / string / bool / object
    if (
        isinstance(series.dtype, pd.CategoricalDtype)
        or pd.api.types.is_string_dtype(series)
        or pd.api.types.is_bool_dtype(series)
        or pd.api.types.is_object_dtype(series)
    ):
        top = series.value_counts(dropna=True).head(5)
        return {
            "type": "categorical",
            "dtype": dtype_str,
            "null_count": null_count,
            "nunique": int(series.nunique()),
            "top_values": [
                {"value": str(k), "count": int(v)} for k, v in top.items()
            ],
        }

    # Fallback
    return {
        "type": "other",
        "dtype": dtype_str,
        "null_count": null_count,
        "nunique": int(series.nunique()) if hasattr(series, "nunique") else None,
    }


def dataframe_summary(df, max_rows=10):
    """Return first max_rows rows + per-column summaries."""
    rows = df.head(max_rows).copy()
    # Convert index to column for display
    rows = rows.reset_index()

    # Serialize rows safely
    serialized_rows = []
    for _, row in rows.iterrows():
        r = {}
        for col in rows.columns:
            val = row[col]
            if pd.isna(val) if not isinstance(val, (list, dict, np.ndarray)) else False:
                r[str(col)] = None
            elif isinstance(val, (np.integer,)):
                r[str(col)] = int(val)
            elif isinstance(val, (np.floating,)):
                r[str(col)] = float(val)
            else:
                r[str(col)] = str(val)
        serialized_rows.append(r)

    columns = list(rows.columns)
    summaries = {}
    for col in rows.columns:   # includes the reset index column(s)
        summaries[str(col)] = summarize_series(rows[col])

    return {
        "columns": [str(c) for c in columns],
        "rows": serialized_rows,
        "summaries": summaries,
    }


def matrix_preview(matrix, row_names, col_names, max_rows=10):
    """Preview of a dense/sparse matrix as a dataframe-like structure."""
    try:
        n_rows = min(max_rows, matrix.shape[0])
        n_cols = min(50, matrix.shape[1])  # cap columns for display

        chunk = matrix[:n_rows, :n_cols]
        if hasattr(chunk, "toarray"):
            data = chunk.toarray()
        else:
            data = np.array(chunk)

        df = pd.DataFrame(
            data,
            index=row_names[:n_rows] if row_names is not None else range(n_rows),
            columns=col_names[:n_cols] if col_names is not None else range(n_cols),
        )
        return dataframe_summary(df, max_rows=max_rows)
    except Exception as e:
        return {"error": str(e), "columns": [], "rows": [], "summaries": {}}


def read_h5ad(path):
    import anndata as ad

    adata = ad.read_h5ad(path, backed="r")

    result = {}

    # --- Shape ---
    result["shape"] = {"n_obs": adata.n_obs, "n_vars": adata.n_vars}

    # --- obs ---
    result["obs"] = dataframe_summary(adata.obs)

    # --- var ---
    result["var"] = dataframe_summary(adata.var)

    # --- obsm ---
    result["obsm"] = {}
    for key in adata.obsm_keys():
        m = adata.obsm[key]
        shape = list(m.shape) if hasattr(m, "shape") else [adata.n_obs, "?"]
        result["obsm"][key] = {"shape": shape}

    # --- varm ---
    result["varm"] = {}
    for key in adata.varm_keys():
        m = adata.varm[key]
        shape = list(m.shape) if hasattr(m, "shape") else [adata.n_vars, "?"]
        result["varm"][key] = {"shape": shape}

    # --- obsp ---
    result["obsp"] = {}
    for key in adata.obsp.keys():
        m = adata.obsp[key]
        shape = list(m.shape) if hasattr(m, "shape") else [adata.n_obs, adata.n_obs]
        result["obsp"][key] = {"shape": shape}

    # --- varp ---
    result["varp"] = {}
    for key in adata.varp.keys():
        m = adata.varp[key]
        shape = list(m.shape) if hasattr(m, "shape") else [adata.n_vars, adata.n_vars]
        result["varp"][key] = {"shape": shape}

    # --- layers ---
    result["layers"] = {}
    for key in adata.layers.keys():
        m = adata.layers[key]
        shape = list(m.shape) if hasattr(m, "shape") else [adata.n_obs, adata.n_vars]
        norm = infer_normalization(m, name=f"layers['{key}']")
        result["layers"][key] = {"shape": shape, "normalization": norm}

    # --- uns ---
    result["uns_keys"] = list(adata.uns.keys())

    # --- X normalization ---
    result["X_normalization"] = infer_normalization(adata.X, name="X")

    # --- raw slot ---
    result["has_raw"] = adata.raw is not None

    # --- UMAP ---
    result["umap"] = None
    if "X_umap" in adata.obsm:
        umap_coords = adata.obsm["X_umap"]
        if hasattr(umap_coords, "toarray"):
            umap_coords = umap_coords.toarray()
        umap_coords = np.array(umap_coords)

        # Take first 50k cells (sequential slice; coords already loaded into numpy)
        n = umap_coords.shape[0]
        if n > 50000:
            umap_coords = umap_coords[:50000]
            obs_subset = adata.obs.iloc[:50000]
        else:
            obs_subset = adata.obs

        # Collect categorical obs columns for coloring
        color_options = [
            col for col in obs_subset.columns
            if pd.api.types.is_categorical_dtype(obs_subset[col])
            or pd.api.types.is_object_dtype(obs_subset[col])
            or pd.api.types.is_bool_dtype(obs_subset[col])
        ]

        color_data = {}
        for col in color_options[:10]:  # cap at 10 color options
            color_data[col] = [str(v) for v in obs_subset[col].tolist()]

        result["umap"] = {
            "x": umap_coords[:, 0].tolist(),
            "y": umap_coords[:, 1].tolist(),
            "color_options": color_options[:10],
            "color_data": color_data,
        }

    adata.file.close()
    return result


def fetch_slot(path, slot, key=None):
    """
    Fetch full preview for a specific slot when user clicks.
    slot: 'obs' | 'var' | 'obsm' | 'varm' | 'obsp' | 'varp' | 'layers' | 'X'
    key: sub-key for obsm/varm/obsp/varp/layers
    """
    import anndata as ad

    adata = ad.read_h5ad(path, backed="r")
    out = {}

    if slot == "obs":
        out = dataframe_summary(adata.obs)
    elif slot == "var":
        out = dataframe_summary(adata.var)
    elif slot == "obsm" and key:
        m = adata.obsm[key]
        out = matrix_preview(m, list(adata.obs_names), None)
    elif slot == "varm" and key:
        m = adata.varm[key]
        out = matrix_preview(m, list(adata.var_names), None)
    elif slot == "obsp" and key:
        m = adata.obsp[key]
        out = matrix_preview(m, list(adata.obs_names), list(adata.obs_names))
    elif slot == "varp" and key:
        m = adata.varp[key]
        out = matrix_preview(m, list(adata.var_names), list(adata.var_names))
    elif slot == "layers" and key:
        m = adata.layers[key]
        out = matrix_preview(m, list(adata.obs_names), list(adata.var_names))
    elif slot == "X":
        out = matrix_preview(adata.X, list(adata.obs_names), list(adata.var_names))
    elif slot == "uns" and key:
        val = adata.uns.get(key)
        try:
            # Try to render as a DataFrame if it's array-like
            import pandas as _pd
            if hasattr(val, "keys"):  # dict
                rows = [{"key": str(k), "value": str(v)} for k, v in val.items()]
                out = {"columns": ["key", "value"], "rows": rows[:50], "summaries": {}}
            elif hasattr(val, "__len__") and not isinstance(val, str):
                import numpy as _np
                arr = _np.array(val)
                if arr.ndim == 2:
                    df = _pd.DataFrame(arr[:10])
                    out = dataframe_summary(df)
                else:
                    rows = [{"index": str(i), "value": str(v)} for i, v in enumerate(arr[:50])]
                    out = {"columns": ["index", "value"], "rows": rows, "summaries": {}}
            else:
                out = {"columns": ["value"], "rows": [{"value": str(val)}], "summaries": {}}
        except Exception as e:
            out = {"columns": ["value"], "rows": [{"value": str(val)}], "summaries": {}}

    adata.file.close()
    print(json.dumps(out))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: reader.py <file.h5ad> [slot] [key]"}))
        sys.exit(1)

    filepath = sys.argv[1]

    if len(sys.argv) == 2:
        # Full summary
        try:
            result = read_h5ad(filepath)
            print(json.dumps(result))
        except Exception as e:
            print(json.dumps({"error": str(e)}))
            sys.exit(1)
    else:
        # Slot fetch: reader.py <file> <slot> [key]
        slot = sys.argv[2]
        key = sys.argv[3] if len(sys.argv) > 3 else None
        try:
            fetch_slot(filepath, slot, key)
        except Exception as e:
            print(json.dumps({"error": str(e)}))
            sys.exit(1)
