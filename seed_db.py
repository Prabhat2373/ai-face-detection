#!/usr/bin/env python3
"""
Seed script to populate the SQLite database with test data:
- Departments (HR, Engineering, Operations, Sales, Marketing)
- Employees (25 sample employees across departments)
- Attendance records (30 days of past attendance with random check-in/check-out timestamps)
- Alarm records / events
- Sample cameras
"""

import json
import random
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from python_recognizer.store import SQLiteStore, get_canonical_db_path, iso_now


def seed_database(count_employees=2000, days_history=300):
    db_path = get_canonical_db_path()
    print(f"Seeding database at: {db_path} (Employees: {count_employees}, Days: {days_history})...")
    store = SQLiteStore(db_path)
    tenant_id = "default"
    store.ensure_tenant(tenant_id, "Local Tenant")

    # 1. Seed Departments
    departments_data = [
        {"name": "Engineering", "description": "Software development and AI engineering"},
        {"name": "Human Resources", "description": "HR management and talent acquisition"},
        {"name": "Operations", "description": "Facility management and logistics"},
        {"name": "Sales & Marketing", "description": "Client acquisition and branding"},
        {"name": "Executive", "description": "Management and leadership team"},
        {"name": "Customer Support", "description": "Customer service and technical assistance"},
        {"name": "Finance & Accounting", "description": "Financial planning and bookkeeping"},
        {"name": "Legal & Compliance", "description": "Legal counsel and policy oversight"},
    ]

    existing_depts = {d["name"]: d["id"] for d in store.list_departments(tenant_id)}
    dept_ids = []
    for dept in departments_data:
        if dept["name"] in existing_depts:
            dept_ids.append(existing_depts[dept["name"]])
        else:
            res = store.upsert_department(dept, tenant_id)
            dept_ids.append(res["id"])
    print(f"✓ Ensured {len(dept_ids)} departments")

    # 2. Seed Cameras
    cameras_data = [
        {"name": "Main Entrance Cam 01", "camera_role": "gate", "rtsp_url": "rtsp://192.168.1.101:554/stream1", "enabled": 1, "department_id": dept_ids[2]},
        {"name": "Reception Lobby Cam 02", "camera_role": "reception", "rtsp_url": "rtsp://192.168.1.102:554/stream1", "enabled": 1, "department_id": dept_ids[1]},
        {"name": "Engineering Bay Cam 03", "camera_role": "general", "rtsp_url": "rtsp://192.168.1.103:554/stream1", "enabled": 1, "department_id": dept_ids[0]},
        {"name": "West Gate Cam 04", "camera_role": "gate", "rtsp_url": "rtsp://192.168.1.104:554/stream1", "enabled": 1, "department_id": dept_ids[2]},
        {"name": "Cafeteria Exit Cam 05", "camera_role": "general", "rtsp_url": "rtsp://192.168.1.105:554/stream1", "enabled": 1, "department_id": dept_ids[3]},
    ]
    for cam in cameras_data:
        store.upsert_camera(cam, tenant_id)
    print(f"✓ Ensured {len(cameras_data)} sample cameras")

    # 3. Seed Employees (Bulk insertion for high performance)
    first_names = ["Alex", "Jordan", "Taylor", "Morgan", "Sam", "Chris", "Pat", "Riley", "Casey", "Avery", "Dakota", "Reese", "Quinn", "Skyler", "Cameron", "Jamie", "Peyton", "Kendall", "Hayden", "Emerson", "Rowan", "Finley", "Sawyer", "Elliot", "Kai", "Noah", "Liam", "Oliver", "Elijah", "Lucas", "Ethan", "Leo", "Ezra", "Luca", "Asher", "Mateo", "Benjamin", "James", "Benjamin", "Lucas", "Mason"]
    last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson", "White", "Harris", "Clark", "Lewis", "Robinson", "Walker", "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green", "Adams"]
    roles = ["Software Engineer", "HR Specialist", "Operations Manager", "Sales Lead", "Product Manager", "QA Analyst", "UI/UX Designer", "Support Engineer", "Financial Analyst", "Compliance Officer"]

    now_str = iso_now()
    existing_emp_count = len(store.list_employees(tenant_id))
    
    employees = []
    if existing_emp_count < count_employees:
        print(f"Generating {count_employees - existing_emp_count} new employees...")
        with store.connection() as conn:
            for i in range(existing_emp_count, count_employees):
                fn = first_names[i % len(first_names)]
                ln = last_names[(i * 3 + i // len(first_names)) % len(last_names)]
                name = f"{fn} {ln} #{i+1}"
                emp_code = f"EMP-{10000 + i}"
                role = random.choice(roles)
                dept_id = random.choice(dept_ids)
                emp_id = f"emp-{uuid.uuid4().hex[:12]}"

                conn.execute(
                    """
                    INSERT INTO employees (id, tenant_id, name, employee_code, role, active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                    """,
                    (emp_id, tenant_id, name, emp_code, role, now_str, now_str)
                )
                conn.execute(
                    "INSERT OR IGNORE INTO employee_departments (employee_id, department_id, created_at) VALUES (?, ?, ?)",
                    (emp_id, dept_id, now_str)
                )
                conn.execute("INSERT OR REPLACE INTO known_faces (label, updated_at) VALUES (?, ?)", (name, now_str))
                dummy_vec = [round(random.uniform(-0.1, 0.1), 4) for _ in range(512)]
                conn.execute(
                    "INSERT INTO face_embeddings (label, employee_id, embedding, created_at) VALUES (?, ?, ?, ?)",
                    (name, emp_id, json.dumps(dummy_vec), now_str)
                )
                employees.append({"id": emp_id, "name": name, "role": role})
    else:
        employees = store.list_employees(tenant_id)[:count_employees]

    print(f"✓ Total {len(employees)} active employees in system")

    # 4. Seed Bulk Attendance Records over 300 Days (Batch SQL transaction for speed)
    today = datetime.now(timezone.utc).date()
    attendance_batch = []
    batch_size = 5000
    total_attendance = 0

    print(f"Bulk generating attendance records for {days_history} days...")
    with store.connection() as conn:
        for day_offset in range(days_history, -1, -1):
            date_obj = today - timedelta(days=day_offset)
            date_str = date_obj.isoformat()
            
            # 85% attendance rate per day
            daily_present = random.sample(employees, k=min(len(employees), int(len(employees) * random.uniform(0.75, 0.92))))

            for emp in daily_present:
                checkin_hour = random.randint(8, 10)
                checkin_minute = random.randint(0, 59)
                first_app = datetime(date_obj.year, date_obj.month, date_obj.day, checkin_hour, checkin_minute, tzinfo=timezone.utc).isoformat()
                
                checkout_hour = random.randint(17, 19)
                checkout_minute = random.randint(0, 59)
                last_app = datetime(date_obj.year, date_obj.month, date_obj.day, checkout_hour, checkout_minute, tzinfo=timezone.utc).isoformat()

                cam = random.choice(cameras_data)
                dept_name = random.choice(departments_data)["name"]
                label_key = f"{tenant_id}::{emp['name']}::{date_str}"

                attendance_batch.append((
                    label_key,
                    emp["name"],
                    date_str,
                    first_app,
                    last_app,
                    cam["camera_role"],
                    cam["camera_role"],
                    cam["name"],
                    cam["name"],
                    cam["name"],
                    cam["name"],
                    dept_name,
                    dept_name,
                    round(random.uniform(0.75, 0.98), 2),
                    random.randint(10, 150),
                    round(random.uniform(0.88, 0.99), 2),
                ))

                if len(attendance_batch) >= batch_size:
                    conn.executemany(
                        """
                        INSERT OR REPLACE INTO attendance_records (
                            label, person_label, attendance_date, first_appearance, last_appearance,
                            first_camera_role, last_camera_role, first_camera_id, last_camera_id,
                            first_camera_name, last_camera_name, first_department_name, last_department_name,
                            last_confidence, appearances, max_confidence
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        attendance_batch
                    )
                    total_attendance += len(attendance_batch)
                    attendance_batch.clear()

        if attendance_batch:
            conn.executemany(
                """
                INSERT OR REPLACE INTO attendance_records (
                    label, person_label, attendance_date, first_appearance, last_appearance,
                    first_camera_role, last_camera_role, first_camera_id, last_camera_id,
                    first_camera_name, last_camera_name, first_department_name, last_department_name,
                    last_confidence, appearances, max_confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                attendance_batch
            )
            total_attendance += len(attendance_batch)
            attendance_batch.clear()

    print(f"✓ Generated {total_attendance:,} total attendance records over {days_history} days!")

    # 5. Seed Alarms / Sync Events
    with store.connection() as conn:
        for day_offset in range(30, -1, -1):
            date_obj = today - timedelta(days=day_offset)
            if random.random() > 0.3:
                alarm_time = datetime(date_obj.year, date_obj.month, date_obj.day, random.randint(9, 18), random.randint(0, 59), tzinfo=timezone.utc).isoformat()
                cam = random.choice(cameras_data)
                alarm_record = {
                    "reason": "unknown_person",
                    "cameraRole": cam["camera_role"],
                    "cameraId": cam["name"],
                    "cameraName": cam["name"],
                    "timestamp": alarm_time,
                    "faces": [{"match": {"label": None, "confidence": round(random.uniform(0.65, 0.85), 2)}}],
                    "snapshot": None
                }
                store.enqueue_sync_event("alarm.triggered", alarm_record)

    print("✓ Created sample unknown person alarm events")
    print(f"\nSuccessfully seeded {total_attendance:,} attendance records for {count_employees:,} employees!")


if __name__ == "__main__":
    seed_database(count_employees=2000, days_history=300)
