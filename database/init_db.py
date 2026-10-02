from database.connection import engine
from database.models import Base


# ==================================================
# CREATE DATABASE TABLES
# ==================================================

Base.metadata.create_all(bind=engine)


print("ENTORA database tables created successfully!")