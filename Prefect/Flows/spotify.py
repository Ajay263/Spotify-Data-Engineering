import os
import pandas as pd
import numpy as np
import time
import pyarrow as pa
from random import randint

from pathlib import Path
from prefect import flow, task
from prefect.tasks import task_input_hash
from datetime import timedelta, datetime
from prefect_gcp.cloud_storage import GcsBucket
from prefect_gcp import GcpCredentials
from kaggle.api.kaggle_api_extended import KaggleApi
import logging
from prefect.filesystems import GCS

@task(log_prints=True, tags=["extract"])
def extract_data() -> pd.DataFrame:
    """Download Spotify  data from Kaggle API into Pandas DataFrame"""

    try:
        os.environ['KAGGLE_USERNAME'] = "alexiojunioraaron"
        os.environ['KAGGLE_KEY'] = "ffc4d41937e4683dceeb8151ef0a60db"
        api = KaggleApi()
        api.authenticate()
        api.dataset_download_files('rodolfofigueroa/spotify-12m-songs', path="dataset")
    except Exception as e:
        logging.error(f"Failed to download data from Kaggle API: {str(e)}")
        return None

    try:
        df = pd.read_csv('dataset/spotify-12m-songs.zip', compression='zip')
    except Exception as e:
        logging.error(f"Failed to read data into Pandas DataFrame: {str(e)}")
        return None
    
    return df


@task(log_prints=True)
def clean(df: pd.DataFrame) -> pd.DataFrame:
   """Some pandas transforms and print basic info"""
   
   df = df.drop(['id', 'album_id', 'artist_ids', 'track_number', 'disc_number', 'time_signature'], axis=1)
   df.loc[815351:815360,'year'] = 2018
   df.loc[450071:450076,'year'] = 1996
   df.loc[459980:459987,'year'] = 1991
   df['artists'] = df['artists'].str.strip("['']")
   df['danceability'] = df['danceability'].round(2)
   df['energy'] = df['energy'].round(2)
   df['loudness'] = df['loudness'].round(2)
   df['speechiness'] = df['speechiness'].round(2)
   df['acousticness'] = df['acousticness'].round(2)
   df['instrumentalness'] = df['instrumentalness'].round(2)
   df['liveness'] = df['liveness'].round(2)
   df['valence'] = df['valence'].round(2)
   df["tempo"] = df["tempo"].astype(int)
   df['year_date'] = pd.to_datetime(df['year'], format='%Y')
   df["duration_s"] = (df["duration_ms"] / 1000).astype(int).round(0)
   
   print(df.head(2))
   print(f"columns: {df.dtypes}")
   print(f"rows: {len(df)}")
   return df


@task(log_prints=True)
def write_local(df_transformed: pd.DataFrame) -> Path:
    """Write dataframe locally as parquet file"""

    parquet_path = Path(f"dataset/spotify-12m-songs.parquet")
    df_transformed.to_parquet(parquet_path, compression="gzip")
    
    return parquet_path

@task(log_prints=True)
def write_gcs(parquet_path: Path) -> None:
    """Upload local parquet file into GCS Bucket"""
    gcp_cloud_storage_bucket_block = GcsBucket.load("googlecloud-connector")
    gcp_cloud_storage_bucket_block.upload_from_path(from_path=parquet_path, to_path=parquet_path)

    return

@task(log_prints=True)
def extract_from_gcs(parquet_path: Path) -> Path:
    """Download data from GCS"""
    gcp_cloud_storage_bucket_block = GcsBucket.load("googlecloud-connector")
    gcp_cloud_storage_bucket_block.get_directory(from_path=parquet_path, local_path=f"dataset/")
    
    return Path(f"{parquet_path}")

@task(log_prints=True)
def write_bq(path: Path) -> None:
    """Read parquet file and write dataframe to BigQuery"""
    df_final = pd.read_parquet(path)

    gcp_credentials_block = GcpCredentials.load("gcs-connector")

    df_final.to_gbq(
        destination_table="github_archive_de.spotify",
        project_id="github-archive-de",
        credentials=gcp_credentials_block.get_credentials_from_service_account(),
        chunksize=500_000,
        if_exists="replace",
    )

    return

@flow(name="Ingest Data")
def main_flow(table_name: str = "Spotify") -> None:
    """Main ETL flow to ingest data"""
    
    raw_data = extract_data()
    df_transformed = clean(raw_data)
    parquet_path = write_local(df_transformed)

    write_gcs(parquet_path)
    path = extract_from_gcs(parquet_path)
    write_bq(path)

if __name__ == "__main__":
    main_flow()
    
    
    
    
