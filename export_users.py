from pathlib import Path

from openpyxl import Workbook

from app import create_app
from models import User, db


def export_users():
    app = create_app()
    with app.app_context():
        users = User.query.order_by(User.id).all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Users"
    ws.append(["id", "first_name", "last_name", "phone", "email", "created_at"])
    for user in users:
        ws.append(
            [
                user.id,
                user.first_name,
                user.last_name,
                user.phone,
                user.email,
                user.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            ]
        )

    exports_dir = Path("exports")
    exports_dir.mkdir(parents=True, exist_ok=True)
    output_path = exports_dir / "users.xlsx"
    wb.save(output_path)
    print(f"Exported {len(users)} users to {output_path}")


if __name__ == "__main__":
    export_users()
