import logging
import posixpath
import tempfile
import uuid
from pathlib import Path
from typing import Callable, Dict, Optional

import pandas as pd
import yaml
from zstandard import ZstdDecompressor

from giskard.client.giskard_client import GiskardClient
from giskard.client.io_utils import save_df, compress
from giskard.core.core import DatasetMeta
from giskard.settings import settings

logger = logging.getLogger(__name__)


class Dataset:
    name: str
    target: str
    feature_types: Dict[str, str]
    column_types: Dict[str, str]
    df: pd.DataFrame

    def __init__(
            self,
            df: pd.DataFrame,
            name: Optional[str] = None,
            target: Optional[str] = None,
            feature_types: Dict[str, str] = None,
            column_types: Dict[str, str] = None,
    ) -> None:
        self.name = name
        self.df = df
        self.target = target
        self.feature_types = feature_types
        self.column_types = column_types

    def save(self, client: GiskardClient, project_key: str):
        from giskard.core.dataset_validation import validate_dataset

        validate_dataset(dataset=self)

        dataset_id = uuid.uuid4().hex
        with tempfile.TemporaryDirectory(prefix="giskard-dataset-") as local_path:
            original_size_bytes, compressed_size_bytes = self._save_to_local_dir(Path(local_path))
            client.log_artifacts(local_path, posixpath.join(project_key, "datasets", dataset_id))
            client.save_dataset_meta(project_key,
                                     dataset_id,
                                     self.meta,
                                     original_size_bytes=original_size_bytes,
                                     compressed_size_bytes=compressed_size_bytes)
        return dataset_id

    @property
    def meta(self):
        return DatasetMeta(name=self.name,
                           target=self.target,
                           feature_types=self.feature_types,
                           column_types=self.column_types)

    @staticmethod
    def cast_column_to_types(df, column_types):
        current_types = df.dtypes.apply(lambda x: x.name).to_dict()
        logger.info(f"Casting dataframe columns from {current_types} to {column_types}")
        if column_types:
            try:
                df = df.astype(column_types)
            except Exception as e:
                raise ValueError("Failed to apply column types to dataset") from e
        return df

    @classmethod
    def _read_dataset_from_local_dir(cls, local_path: str):
        with open(local_path, 'rb') as ds_stream:
            return pd.read_csv(
                ZstdDecompressor().stream_reader(ds_stream),
                keep_default_na=False,
                na_values=["_GSK_NA_"],
            )

    @classmethod
    def load(cls, client: GiskardClient, project_key, dataset_id):
        local_dir = settings.home_dir / settings.cache_dir / project_key / "datasets" / dataset_id

        if client is None:
            # internal worker case, no token based http client
            assert local_dir.exists(), f"Cannot find existing model {project_key}.{dataset_id}"
            with open(Path(local_dir) / 'giskard-dataset-meta.yaml') as f:
                meta = DatasetMeta(**yaml.load(f, Loader=yaml.Loader))
        else:
            client.load_artifact(local_dir, posixpath.join(project_key, "datasets", dataset_id))
            meta: DatasetMeta = client.load_dataset_meta(project_key, dataset_id)


        df = cls._read_dataset_from_local_dir(local_dir / "data.csv.zst")
        df = cls.cast_column_to_types(df, meta.column_types)
        return cls(
            df=df,
            **meta.__dict__
        )

    def _save_to_local_dir(self, local_path: Path):
        with open(local_path / "data.csv.zst", 'wb') as f:
            uncompressed_bytes = save_df(self.df)
            compressed_bytes = compress(uncompressed_bytes)
            f.write(compressed_bytes)

            with open(Path(local_path) / 'giskard-dataset-meta.yaml', 'w') as meta_f:
                yaml.dump(self.meta.__dict__, meta_f, default_flow_style=False)
            return len(uncompressed_bytes), len(compressed_bytes)

    @property
    def columns(self):
        return self.df.columns

    def slice(self, slice_fn: Callable):
        if slice_fn is None:
            return self
        return Dataset(
            df=slice_fn(self.df),
            name=self.name,
            target=self.target,
            feature_types=self.feature_types,
            column_types=self.column_types)

    def __len__(self):
        return len(self.df)