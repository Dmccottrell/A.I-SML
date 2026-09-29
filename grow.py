"""
grow.py - Make a deeper model out of a trained one ("depth up-scaling").

WHAT THIS FILE DOES
    Instead of starting a bigger model from random numbers, we start from a smaller model that
    is already trained and give it more layers by COPYING some of its own layers. Training then
    continues on the bigger model. Everything the small model learned is the starting point.

        old model, 4 layers:      [A] [B] [C] [D]
        "stack" to 8 layers:      [A] [B] [C] [D] [A] [B] [C] [D]
        "interleave" to 8 layers: [A] [A] [B] [B] [C] [C] [D] [D]

    Only the number of layers changes. The width, the tokenizer and the embeddings stay the
    same, which is why a model can only be grown into one that shares its tokenizer and width.
    The optimizer's memory is NOT carried over (the new model starts a fresh optimizer).

    Used by growth_test.py (the experiment that measures how much compute growth really saves).
    The same code will grow Saga into Edda later.

    Right after growing, the model is usually a bit WORSE than before (the copies weren't
    trained to work together), then it recovers quickly. That short dip is normal.
"""
import re

BLOCK = re.compile(r"^blocks\.(\d+)\.(.*)$")


def layer_map(old_layers, new_layers, style="stack"):
    """A list: new layer i is a copy of old layer layer_map[i]."""
    if new_layers < old_layers:
        raise ValueError("growing needs at least as many layers as the old model")
    if style == "stack":            # repeat the whole stack (A B C D A B C D)
        return [i % old_layers for i in range(new_layers)]
    if style == "interleave":       # repeat each layer in place (A A B B C C D D)
        return [min(i * old_layers // new_layers, old_layers - 1) for i in range(new_layers)]
    raise ValueError(f"unknown style {style!r}: use 'stack' or 'interleave'")


def grow_state_dict(state, config, new_layers, style="stack"):
    """(new weights, new config dict) for a model with `new_layers` layers.

    `state` is a model's state_dict; `config` is its ModelConfig as a dict (as saved in checkpoints).
    """
    old_layers = config["n_layers"]
    mapping = layer_map(old_layers, new_layers, style)
    new_state = {}
    for key, tensor in state.items():
        m = BLOCK.match(key)
        if not m:
            new_state[key] = tensor.clone()                      # embeddings, final norm, output layer
    for new_i, old_i in enumerate(mapping):
        for key, tensor in state.items():
            m = BLOCK.match(key)
            if m and int(m.group(1)) == old_i:
                new_state[f"blocks.{new_i}.{m.group(2)}"] = tensor.clone()
    new_config = dict(config, n_layers=new_layers)
    return new_state, new_config
