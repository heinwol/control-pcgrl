from control_pcgrl.envs.reps.representation import (
    EgocentricRepresentation,
    Representation,
)
from PIL import Image
from gymnasium import spaces
import numpy as np

"""
The wide representation where the agent can pick the tile position and tile value at each update.
"""


class WideRepresentation(Representation):
    """
    Initialize all the parameters used by that representation
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    """
    Gets the action space used by the wide representation

    Parameters:
        width: the current map width
        height: the current map height
        num_tiles: the total number of the tile values

    Returns:
        MultiDiscrete: the action space used by that wide representation which
        consists of the x position, y position, and the tile value
    """

    def get_action_space(self, dims, num_tiles):
        return spaces.MultiDiscrete([*dims, num_tiles])

    """
    Update the wide representation with the input action

    Parameters:
        action: an action that is used to advance the environment (same as action space)
        
    Returns:
        boolean: True if the action change the map, False if nothing changed
    """

    def update(self, action):
        self._pos = action[
            :-1
        ]  # Agent "chooses" location to act on, record this as our position.
        change = [0, 1][self._map[tuple(action[:-1])] != action[-1]]
        self._map[tuple(action[:-1])] = action[-1]
        super().update(action)
        return change, action[:-1]

    def render(self, lvl_image, tile_size, border_size):
        return EgocentricRepresentation.render(self, lvl_image, tile_size, border_size)
