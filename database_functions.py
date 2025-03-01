import os

import dotenv
from sqlalchemy import create_engine, text


def add_sample_to_db(filename, upload_date, thumbnail, uploader, source_id):
    with engine.connect() as conn:
        try:
            conn.execute(
                text(
                    "INSERT INTO sample (filename, tags, upload_date, thumbnail_filename, uploader, source_id) VALUES (:filename, :tags, :upload_date, :thumbnail_filename, :uploader, :source_id)"),
                {"filename": filename, "tags": [], "upload_date": upload_date, "thumbnail_filename": thumbnail, "uploader": uploader, "source_id": source_id}
            )
            conn.commit()
        except Exception as e:
            print(f"Error adding sample: {e}")


dotenv.load_dotenv()

DATABASE_URL = os.getenv('DATABASE_URL')
engine = create_engine(DATABASE_URL)
