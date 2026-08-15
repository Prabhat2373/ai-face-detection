# PySide6 UI Automated Test Report

**Execution Timestamp**: `2026-08-14 22:00:45`  
**Environment**: PySide6 (Qt offscreen) | Isolated SQLite DB  

## Summary Dashboard

| Metric | Value |
| :--- | :--- |
| **Total Tests** | `11` |
| **Passed** | `3` ✅ |
| **Failed** | `8` ❌ |
| **Success Rate** | **`27.3%`** |
| **Total Duration** | `725.97 ms` |

---

## Page-by-Page Test Breakdown

| Page / Component | Test Description | Status | Duration | Details |
| :--- | :--- | :---: | :---: | :--- |
| **Database Core** | Database & Schema Initialization | ✅ PASS | `1.20 ms` | Database initialized cleanly at /var/folders/lt/xtz0n3hx7djgjblpdqfv18jc0000gn/T/tmp38_r7nh1/test_app.db |
| **Navigation & Sidebar** | Page Switching & Stacked Widget | ❌ FAIL | `506.53 ms` |  `<pre>AttributeError: 'MainWindow' object has no attribute 'stacked_widget'
Traceback (most recent call last):
  File "/Users/prabhattambe/Documents/ai-face-detection/test_ui_app.py", line 108, in run_test_method
    res = test_func(*args, **kwargs)
          ^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/prabhattambe/Documents/ai-face-detection/test_ui_app.py", line 143, in _test
    self.assertIsNotNone(window.stacked_widget)
                         ^^^^^^^^^^^^^^^^^^^^^
AttributeError: 'MainWindow' object has no attribute 'stacked_widget'
</pre>` |
| **Departments Page** | Department CRUD & Search Filter | ❌ FAIL | `105.47 ms` |  `<pre>TypeError: DepartmentsPage._filter_table() missing 1 required positional argument: 'text'
Traceback (most recent call last):
  File "/Users/prabhattambe/Documents/ai-face-detection/test_ui_app.py", line 108, in run_test_method
    res = test_func(*args, **kwargs)
          ^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/prabhattambe/Documents/ai-face-detection/test_ui_app.py", line 188, in _test
    page._filter_table()
TypeError: DepartmentsPage._filter_table() missing 1 required positional argument: 'text'
</pre>` |
| **Cameras Page** | Camera CRUD & Search Filter | ❌ FAIL | `16.51 ms` |  `<pre>TypeError: CamerasPage._filter_table() missing 1 required positional argument: 'text'
Traceback (most recent call last):
  File "/Users/prabhattambe/Documents/ai-face-detection/test_ui_app.py", line 108, in run_test_method
    res = test_func(*args, **kwargs)
          ^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/prabhattambe/Documents/ai-face-detection/test_ui_app.py", line 256, in _test
    page._filter_table()
TypeError: CamerasPage._filter_table() missing 1 required positional argument: 'text'
</pre>` |
| **Employees Page** | Employee CRUD & Search/Dept Filters | ❌ FAIL | `19.85 ms` |  `<pre>AssertionError: 1 != 0
Traceback (most recent call last):
  File "/Users/prabhattambe/Documents/ai-face-detection/test_ui_app.py", line 108, in run_test_method
    res = test_func(*args, **kwargs)
          ^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/prabhattambe/Documents/ai-face-detection/test_ui_app.py", line 330, in _test
    self.assertEqual(page._table.rowCount(), 0)
  File "/Library/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/case.py", line 885, in assertEqual
    assertion_func(first, second, msg=msg)
  File "/Library/Frameworks/Python.framework/Versions/3.12/lib/python3.12/unittest/case.py", line 878, in _baseAssertEqual
    raise self.failureException(msg)
AssertionError: 1 != 0
</pre>` |
| **Attendance Page** | Attendance Filters, Date Ranges & KPIs | ❌ FAIL | `26.62 ms` |  `<pre>AttributeError: 'AttendancePage' object has no attribute '_apply_filter'
Traceback (most recent call last):
  File "/Users/prabhattambe/Documents/ai-face-detection/test_ui_app.py", line 108, in run_test_method
    res = test_func(*args, **kwargs)
          ^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/prabhattambe/Documents/ai-face-detection/test_ui_app.py", line 377, in _test
    page._apply_filter()
    ^^^^^^^^^^^^^^^^^^
AttributeError: 'AttendancePage' object has no attribute '_apply_filter'. Did you mean: '_apply_filters'?
</pre>` |
| **Alarms Page** | Unknown Face Alerts & Clear Action | ❌ FAIL | `0.34 ms` |  `<pre>OperationalError: table sync_events has no column named tenant_id
Traceback (most recent call last):
  File "/Users/prabhattambe/Documents/ai-face-detection/test_ui_app.py", line 108, in run_test_method
    res = test_func(*args, **kwargs)
          ^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/prabhattambe/Documents/ai-face-detection/test_ui_app.py", line 397, in _test
    conn.execute(
sqlite3.OperationalError: table sync_events has no column named tenant_id
</pre>` |
| **Dashboard Page** | Dashboard Stats & Activity Feed | ❌ FAIL | `19.72 ms` |  `<pre>AttributeError: 'DashboardPage' object has no attribute 'search_input'
Traceback (most recent call last):
  File "/Users/prabhattambe/Documents/ai-face-detection/test_ui_app.py", line 108, in run_test_method
    res = test_func(*args, **kwargs)
          ^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/prabhattambe/Documents/ai-face-detection/test_ui_app.py", line 452, in _test
    page.search_input.setText("Filter query")
    ^^^^^^^^^^^^^^^^^
AttributeError: 'DashboardPage' object has no attribute 'search_input'
</pre>` |
| **Live Detection Page** | Camera Feed View & Layout Grid | ✅ PASS | `4.32 ms` | Live Detection camera layout and feed container verified |
| **Reports & Analytics** | Charts & Analytical Breakdown | ✅ PASS | `20.01 ms` | Reports and analytics stats calculation and charts verified |
| **Settings Page** | Performance Profiles & Config Save | ❌ FAIL | `5.39 ms` |  `<pre>TypeError: SettingsPage._update_profile_description() takes 1 positional argument but 2 were given
Traceback (most recent call last):
  File "/Users/prabhattambe/Documents/ai-face-detection/test_ui_app.py", line 108, in run_test_method
    res = test_func(*args, **kwargs)
          ^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/prabhattambe/Documents/ai-face-detection/test_ui_app.py", line 513, in _test
    page._update_profile_description(idx)
TypeError: SettingsPage._update_profile_description() takes 1 positional argument but 2 were given
</pre>` |
