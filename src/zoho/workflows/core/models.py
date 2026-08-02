from typing import Any

class DotDict(dict):
    """
    A dictionary subclass that allows dot-notation (attribute) access
    while preserving standard key lookup and dictionary capabilities.
    """
    def __getattribute__(self, name: str) -> Any:
        # Check if the name is a key in the dictionary first to prioritize keys over dict methods
        if dict.__contains__(self, name):
            value = dict.__getitem__(self, name)
            # Recursively wrap child dictionaries into DotDict for nested dot access
            if isinstance(value, dict) and not isinstance(value, DotDict):
                value = DotDict(value)
                dict.__setitem__(self, name, value)
            elif isinstance(value, list):
                wrapped_list = []
                for item in value:
                    if isinstance(item, dict) and not isinstance(item, DotDict):
                        wrapped_list.append(DotDict(item))
                    elif isinstance(item, tuple):
                        wrapped_tuple = tuple(
                            DotDict(t) if isinstance(t, dict) and not isinstance(t, DotDict) else t
                            for t in item
                        )
                        wrapped_list.append(wrapped_tuple)
                    else:
                        wrapped_list.append(item)
                value = wrapped_list
                dict.__setitem__(self, name, value)
            return value
            
        # Fall back to standard attribute resolution (e.g. methods like .keys(), .items())
        try:
            return super().__getattribute__(name)
        except AttributeError:
            raise AttributeError(f"'DotDict' object has no attribute '{name}'")
            
    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value

    def __delattr__(self, name: str) -> None:
        try:
            del self[name]
        except KeyError:
            raise AttributeError(f"'DotDict' object has no attribute '{name}'")
