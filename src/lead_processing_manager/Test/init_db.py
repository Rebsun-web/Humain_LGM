from lead_processing_manager.Models.models import Base, engine
from lead_processing_manager.Views.excel_handler import ExcelHandler
from lead_processing_manager.Utils.db_utils import db_session


def main():
    print("Creating database tables...")
    Base.metadata.create_all(engine)
    print("✅ Database initialized")

    # Optional: Import existing leads
    handler = ExcelHandler()
    new_leads = handler.check_for_new_leads()
    if new_leads:
        with db_session() as db:
            handler.add_leads_to_database(new_leads, db)
            print(f"✅ Imported {len(new_leads)} leads")


if __name__ == "__main__":
    main()
