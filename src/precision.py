"""Optional 16-bit (mixed precision) model compute, selected by the HRRRCAST_TF_PRECISION env var."""

import copy
import logging
import os
from typing import Optional

import tensorflow as tf

PRECISION_ENV = "HRRRCAST_TF_PRECISION"
_POLICIES = {"fp32": None, "fp16": "mixed_float16", "bf16": "mixed_bfloat16"}
# InputLayer must stay float32; CastLayer stores its cast target under the "dtype" key.
_SKIP_CLASSES = {"InputLayer", "CastLayer"}

logger = logging.getLogger(__name__)


def get_policy_name() -> Optional[str]:
    """Return the Keras mixed precision policy name, or None for full fp32."""
    value = os.getenv(PRECISION_ENV, "").strip().lower() or "fp32"
    if value not in _POLICIES:
        raise ValueError(
            f"{PRECISION_ENV}={value!r} not recognized; expected one of {sorted(_POLICIES)}"
        )
    return _POLICIES[value]


def _patch_dtypes(obj, policy_name: str) -> int:
    """Recursively replace explicit float32 layer dtypes in a model config; return the count."""
    n = 0
    if isinstance(obj, dict):
        cfg = obj.get("config")
        if (
            isinstance(cfg, dict)
            and obj.get("class_name") not in _SKIP_CLASSES
            and cfg.get("dtype") == "float32"
        ):
            cfg["dtype"] = policy_name
            n += 1
        for v in obj.values():
            n += _patch_dtypes(v, policy_name)
    elif isinstance(obj, list):
        for v in obj:
            n += _patch_dtypes(v, policy_name)
    return n


def apply_from_env(model: tf.keras.Model) -> tf.keras.Model:
    """Rebuild the model with a mixed precision policy if requested; otherwise return it unchanged."""
    policy_name = get_policy_name()
    if policy_name is None:
        logger.info(f"Model compute precision: float32 ({PRECISION_ENV})")
        return model

    # Global policy covers layers created at build time without an explicit dtype.
    tf.keras.mixed_precision.set_global_policy(policy_name)

    # Saved layers carry an explicit float32 dtype, which overrides the global policy.
    config = copy.deepcopy(model.get_config())
    n_patched = _patch_dtypes(config, policy_name)

    new_model = tf.keras.Model.from_config(config)
    new_model.set_weights(model.get_weights())

    if new_model.output.dtype != tf.float32:
        out = tf.keras.layers.Activation("linear", dtype="float32")(new_model.output)
        new_model = tf.keras.Model(new_model.inputs, out)

    logger.info(
        f"Model compute precision: {policy_name} ({PRECISION_ENV}); "
        f"{n_patched} layer dtypes patched"
    )
    return new_model
