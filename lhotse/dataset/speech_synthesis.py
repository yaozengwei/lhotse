from typing import Callable, Dict, List, Sequence, Union

import torch

from lhotse import validate
from lhotse.cut import CutSet
from lhotse.dataset.collation import TokenCollater, collate_audio
from lhotse.dataset.input_strategies import BatchIO, PrecomputedFeatures
from lhotse.utils import ifnone


class SpeechSynthesisDataset(torch.utils.data.Dataset):
    """
    The PyTorch Dataset for the speech synthesis task.
    Each item in this dataset is a dict of:

    .. code-block::

        {
            'audio': (B x NumSamples) float tensor
            'features': (B x NumFrames x NumFeatures) float tensor
            'tokens': (B x NumTokens) long tensor  # when return_tokens=True
            'audio_lens': (B, ) int tensor
            'features_lens': (B, ) int tensor
            'tokens_lens': (B, ) int tensor  # when return_tokens=True
            'text': List[str] of len B  # when return_tokens=False
            'cut': List of Cuts  # when return_cuts=True
        }
    """

    def __init__(
        self,
        return_cuts: bool = False,
        cuts: CutSet = None,
        cut_transforms: List[Callable[[CutSet], CutSet]] = None,
        feature_input_strategy: BatchIO = PrecomputedFeatures(),
        feature_transforms: Union[Sequence[Callable], Callable] = None,
        return_tokens: bool = True,
        add_eos: bool = True,
        add_bos: bool = True,
    ) -> None:
        super().__init__()
        self.return_cuts = return_cuts

        self.return_tokens = return_tokens
        if return_tokens:
            assert cuts is not None, "cuts is required when return_tokens=True"
            self.cuts = cuts
            self.token_collater = TokenCollater(cuts, add_eos=add_eos, add_bos=add_bos)

        self.cut_transforms = ifnone(cut_transforms, [])
        self.feature_input_strategy = feature_input_strategy

        if feature_transforms is None:
            feature_transforms = []
        elif not isinstance(feature_transforms, Sequence):
            feature_transforms = [feature_transforms]

        assert all(
            isinstance(transform, Callable) for transform in feature_transforms
        ), "Feature transforms must be Callable"
        self.feature_transforms = feature_transforms

    def __getitem__(self, cuts: CutSet) -> Dict[str, torch.Tensor]:
        validate_for_tts(cuts)

        for transform in self.cut_transforms:
            cuts = transform(cuts)

        audio, audio_lens = collate_audio(cuts)
        features, features_lens = self.feature_input_strategy(cuts)

        for transform in self.feature_transforms:
            features = transform(features)

        batch = {
            "audio": audio,
            "features": features,
            "audio_lens": audio_lens,
            "features_lens": features_lens,
        }

        if self.return_cuts:
            batch["cut"] = [cut for cut in cuts]

        if self.return_tokens:
            tokens, tokens_lens = self.token_collater(cuts)
            batch["tokens"] = tokens
            batch["tokens_lens"] = tokens_lens
        else:
            # use normalized text
            text = [
                " ".join(sup.normalized_text for sup in cut.supervisions)
                for cut in cuts
            ]
            batch["text"] = text

        return batch


def validate_for_tts(cuts: CutSet) -> None:
    validate(cuts)
    for cut in cuts:
        assert (
            len(cut.supervisions) == 1
        ), "Only the Cuts with single supervision are supported."
