# Clean Refactoring Plan: Pre-Refactor → Tested & Maintainable

## Current State (commit 0921886)

**Good Architecture**:
- ✅ DashboardController (891 lines) - Business logic layer
- ✅ MetricQueryBuilder (604 lines) - Data access layer
- ✅ 5 focused route files (70-350 lines each)
- ✅ Clear separation of concerns
- ⚠️ Uses pandas (needs removal)
- ❌ No tests

**Goal**: Remove pandas while KEEPING the good architecture, then add comprehensive tests.

---

## Phase 1: Remove Pandas (Preserve Architecture) - 3 hours

### Files to Modify:
1. `server/api/metric_queries.py` - Remove pandas, keep all methods
2. `server/api/routes/metrics_routes.py` - Update to use dict/list returns

### Changes:

#### 1.1 Replace `get_raw_timeseries()`
**Current**: Returns `pd.DataFrame`
**New**: Returns `List[Dict[str, Any]]`

```python
# Before (pandas)
def get_raw_timeseries(...) -> pd.DataFrame:
    client_info_df = pd.DataFrame([...])
    int_df = pd.DataFrame(list(int_query))
    float_df = pd.DataFrame(list(float_query))
    df = pd.concat([int_df, float_df])
    return df.merge(client_info_df, on='series')

# After (pure Python)
def get_raw_timeseries(...) -> List[Dict[str, Any]]:
    # Build client info lookup
    client_info = {s.id: {'client_id': s.client.id, 'client_name': s.client.hostname}
                   for s in series_list}

    # Collect points
    points = []
    for point in int_query:
        points.append({
            'timestamp': point['timestamp'],
            'value': float(point['value']),
            'series': point['series_id'],
            **client_info[point['series_id']]
        })

    for point in float_query:
        points.append({
            'timestamp': point['timestamp'],
            'value': point['value'],
            'series': point['series_id'],
            **client_info[point['series_id']]
        })

    # Sort by timestamp
    points.sort(key=lambda x: x['timestamp'])
    return points
```

#### 1.2 Replace `get_timeseries_data()`
**Current**: Returns `pd.DataFrame` with groupby aggregation
**New**: Returns `List[Tuple[int, List[float]]]` (timestamp, values_per_client)

```python
# Before (pandas)
def get_timeseries_data(...) -> pd.DataFrame:
    df = get_raw_timeseries(...)
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='s')
    result = df.groupby(['datetime', 'client_id'])['value'].agg(aggregation)
    return result

# After (pure Python)
def get_timeseries_data(...) -> List[Tuple[int, List[float]]]:
    raw_points = get_raw_timeseries(...)

    # Group by timestamp and client_id
    grouped = {}
    for point in raw_points:
        key = (point['timestamp'], point['client_id'])
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(point['value'])

    # Apply aggregation
    result = {}
    for (timestamp, client_id), values in grouped.items():
        if timestamp not in result:
            result[timestamp] = []

        if aggregation == 'max':
            result[timestamp].append(max(values))
        elif aggregation == 'min':
            result[timestamp].append(min(values))
        elif aggregation == 'avg':
            result[timestamp].append(sum(values) / len(values))
        elif aggregation == 'sum':
            result[timestamp].append(sum(values))

    # Return sorted by timestamp
    return sorted(result.items())
```

#### 1.3 Replace `calculate_rates_from_raw_data()`
**Current**: Uses pandas `pd.to_datetime()` and `groupby()`
**New**: Pure Python rate calculation

```python
# Before (pandas)
def calculate_rates_from_raw_data(df: pd.DataFrame, rate_window_minutes: int = 5) -> pd.DataFrame:
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='s')
    result_groups = []
    for (client_id, series), group in df.groupby(['client_id', 'series']):
        # pandas operations...
    return pd.concat(result_groups)

# After (pure Python)
def calculate_rates_from_raw_data(points: List[Dict], rate_window_minutes: int = 5) -> List[Dict]:
    # Group by client_id and series
    grouped = {}
    for point in points:
        key = (point['client_id'], point['series'])
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(point)

    # Calculate rates for each group
    result = []
    for (client_id, series), group_points in grouped.items():
        group_points.sort(key=lambda x: x['timestamp'])

        for i in range(1, len(group_points)):
            prev = group_points[i-1]
            curr = group_points[i]
            time_diff = curr['timestamp'] - prev['timestamp']

            if time_diff > 0:
                rate = (curr['value'] - prev['value']) / time_diff
                result.append({
                    'timestamp': curr['timestamp'],
                    'client_id': client_id,
                    'client_name': curr['client_name'],
                    'rate': max(0, rate)  # Handle counter resets
                })

    return result
```

**Impact**:
- ✅ Removes pandas dependency completely
- ✅ Keeps all MetricQueryBuilder methods intact
- ✅ API interface unchanged (routes don't need changes)
- ✅ Performance: Likely faster for small datasets (10-20 clients)

---

## Phase 2: Create Test Infrastructure - 1 hour

### 2.1 Setup pytest

**Create**: `tests/conftest.py`
```python
"""Pytest configuration and fixtures"""
import pytest
import tempfile
import os
from peewee import SqliteDatabase
from server.models import Client, MetricSeries, MetricPointsInt, MetricPointsFloat, db_manager


@pytest.fixture
def test_db():
    """Create a test database"""
    # Use in-memory SQLite for tests
    test_database = SqliteDatabase(':memory:')

    # Bind models to test database
    models = [Client, MetricSeries, MetricPointsInt, MetricPointsFloat]
    test_database.bind(models)
    test_database.connect()
    test_database.create_tables(models)

    yield test_database

    test_database.drop_tables(models)
    test_database.close()


@pytest.fixture
def sample_client(test_db):
    """Create a sample client for testing"""
    client = Client.create(
        hostname="test-host",
        machine_id="test-machine-123",
        public_key="test-key",
        status="online"
    )
    return client


@pytest.fixture
def sample_metrics(test_db, sample_client):
    """Create sample metrics data"""
    import time
    now = int(time.time())

    # Create metric series
    cpu_series = MetricSeries.create(
        client=sample_client,
        metric_name="cpu_usage_percent",
        labels=None
    )

    temp_series = MetricSeries.create(
        client=sample_client,
        metric_name="ipmi_temp_celsius",
        labels='{"sensor": "CPU Temp"}'
    )

    # Create metric points
    for i in range(10):
        MetricPointsFloat.create(
            series=cpu_series,
            timestamp=now - (i * 30),  # Every 30 seconds
            sent_at=now - (i * 30),
            value=50.0 + i
        )

        MetricPointsInt.create(
            series=temp_series,
            timestamp=now - (i * 30),
            sent_at=now - (i * 30),
            value=65 + i
        )

    return {
        'client': sample_client,
        'cpu_series': cpu_series,
        'temp_series': temp_series
    }
```

### 2.2 Create pytest.ini

**Create**: `pytest.ini`
```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts =
    -v
    --tb=short
    --strict-markers
    -ra
markers =
    unit: Unit tests (business logic only)
    integration: Integration tests (with database)
    slow: Slow tests (optional for quick runs)
```

### 2.3 Create requirements-dev.txt

**Create**: `requirements-dev.txt`
```
pytest==7.4.3
pytest-cov==4.1.0
pytest-mock==3.12.0
```

---

## Phase 3: Unit Tests for MetricQueryBuilder - 2 hours

**Create**: `tests/unit/test_metric_queries.py`

```python
"""Unit tests for MetricQueryBuilder"""
import pytest
from server.api.metric_queries import MetricQueryBuilder


class TestFilterSeriesByLabels:
    """Test label filtering logic"""

    def test_filter_with_single_label(self, test_db, sample_metrics):
        """Test filtering by single label"""
        from server.models import MetricSeries

        # Filter for CPU temp sensor
        base_query = MetricSeries.select()
        filtered = MetricQueryBuilder.filter_series_by_labels(
            base_query,
            [{"sensor": "CPU Temp"}]
        )

        result = list(filtered)
        assert len(result) == 1
        assert result[0].metric_name == "ipmi_temp_celsius"

    def test_filter_with_multiple_labels(self, test_db, sample_metrics):
        """Test filtering with OR logic across labels"""
        # Create another temp sensor
        from server.models import MetricSeries
        vrm_series = MetricSeries.create(
            client=sample_metrics['client'],
            metric_name="ipmi_temp_celsius",
            labels='{"sensor": "VRM Temp"}'
        )

        base_query = MetricSeries.select()
        filtered = MetricQueryBuilder.filter_series_by_labels(
            base_query,
            [{"sensor": "CPU Temp"}, {"sensor": "VRM Temp"}]
        )

        result = list(filtered)
        assert len(result) == 2

    def test_filter_no_labels_returns_all(self, test_db, sample_metrics):
        """Test that None filter returns all series"""
        from server.models import MetricSeries

        base_query = MetricSeries.select()
        filtered = MetricQueryBuilder.filter_series_by_labels(base_query, None)

        result = list(filtered)
        assert len(result) >= 2  # At least CPU and temp series


class TestGetLatestMetricValue:
    """Test latest metric value retrieval"""

    def test_get_latest_without_aggregation(self, test_db, sample_metrics):
        """Test getting latest single value"""
        value = MetricQueryBuilder.get_latest_metric_value(
            client_id=sample_metrics['client'].id,
            metric_name="cpu_usage_percent",
            label_filters=None,
            aggregation=None
        )

        assert value is not None
        assert isinstance(value, float)
        assert value == 50.0  # First value we created

    def test_get_latest_with_max_aggregation(self, test_db, sample_metrics):
        """Test max aggregation across series"""
        value = MetricQueryBuilder.get_latest_metric_value(
            client_id=sample_metrics['client'].id,
            metric_name="ipmi_temp_celsius",
            label_filters=[{"sensor": "CPU Temp"}],
            aggregation="max"
        )

        assert value is not None
        assert value == 65.0  # Latest max temp

    def test_get_latest_with_label_filter(self, test_db, sample_metrics):
        """Test filtering by labels"""
        value = MetricQueryBuilder.get_latest_metric_value(
            client_id=sample_metrics['client'].id,
            metric_name="ipmi_temp_celsius",
            label_filters=[{"sensor": "CPU Temp"}],
            aggregation=None
        )

        assert value is not None
        assert value == 65.0

    def test_get_latest_nonexistent_metric_returns_none(self, test_db, sample_metrics):
        """Test that nonexistent metric returns None"""
        value = MetricQueryBuilder.get_latest_metric_value(
            client_id=sample_metrics['client'].id,
            metric_name="nonexistent_metric",
            label_filters=None,
            aggregation=None
        )

        assert value is None


class TestGetRawTimeseries:
    """Test raw timeseries retrieval"""

    def test_get_raw_timeseries_basic(self, test_db, sample_metrics):
        """Test basic timeseries retrieval"""
        import time
        now = int(time.time())

        points = MetricQueryBuilder.get_raw_timeseries(
            metric_name="cpu_usage_percent",
            start_time=now - 600,
            end_time=now,
            client_ids=[sample_metrics['client'].id],
            label_filters=None,
            active_only=False
        )

        assert isinstance(points, list)
        assert len(points) == 10  # We created 10 points
        assert all('timestamp' in p for p in points)
        assert all('value' in p for p in points)
        assert all('client_id' in p for p in points)

    def test_get_raw_timeseries_sorted_by_timestamp(self, test_db, sample_metrics):
        """Test that results are sorted by timestamp"""
        import time
        now = int(time.time())

        points = MetricQueryBuilder.get_raw_timeseries(
            metric_name="cpu_usage_percent",
            start_time=now - 600,
            end_time=now,
            client_ids=[sample_metrics['client'].id],
            active_only=False
        )

        timestamps = [p['timestamp'] for p in points]
        assert timestamps == sorted(timestamps)  # Should be ascending


class TestGetTimeseriesData:
    """Test aggregated timeseries data"""

    def test_get_timeseries_with_max_aggregation(self, test_db, sample_metrics):
        """Test timeseries with max aggregation"""
        import time
        now = int(time.time())

        data = MetricQueryBuilder.get_timeseries_data(
            metric_name="cpu_usage_percent",
            start_time=now - 600,
            end_time=now,
            client_ids=[sample_metrics['client'].id],
            aggregation="max",
            label_filters=None,
            active_only=False
        )

        assert isinstance(data, list)
        assert len(data) > 0
        # Each item is (timestamp, [values])
        assert all(isinstance(item, tuple) for item in data)
        assert all(len(item) == 2 for item in data)
```

---

## Phase 4: Unit Tests for DashboardController - 2 hours

**Create**: `tests/unit/test_dashboard_controller.py`

```python
"""Unit tests for DashboardController"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from server.dashboard.controller import DashboardController


class TestCalculateFraction:
    """Test fraction calculation logic"""

    def test_calculate_fraction_basic(self):
        """Test basic fraction calculation"""
        controller = DashboardController()

        with patch('server.dashboard.controller.MetricQueryBuilder') as mock_qb:
            # Mock numerator = 75, denominator = 100
            mock_qb.get_latest_metric_value.side_effect = [75.0, 100.0]

            column_config = {
                "numerator": {"metric_name": "fs_used_bytes"},
                "denominator": {"metric_name": "fs_total_bytes"},
                "multiply_by": 100
            }

            result = controller._calculate_fraction(client_id=1, column_config=column_config)

            assert result == 75.0  # (75 / 100) * 100

    def test_calculate_fraction_with_zero_denominator(self):
        """Test that zero denominator returns None"""
        controller = DashboardController()

        with patch('server.dashboard.controller.MetricQueryBuilder') as mock_qb:
            mock_qb.get_latest_metric_value.side_effect = [50.0, 0.0]

            column_config = {
                "numerator": {"metric_name": "used"},
                "denominator": {"metric_name": "total"},
                "multiply_by": 1
            }

            result = controller._calculate_fraction(client_id=1, column_config=column_config)

            assert result is None


class TestGetLatestMetric:
    """Test get_latest_metric dispatcher"""

    def test_get_latest_metric_regular(self):
        """Test regular metric retrieval"""
        controller = DashboardController()

        with patch('server.dashboard.controller.MetricQueryBuilder') as mock_qb:
            mock_qb.get_latest_metric_value.return_value = 42.0

            column_config = {
                "metric_name": "cpu_usage_percent",
                "aggregation": "max"
            }

            result = controller.get_latest_metric(client_id=1, column_config=column_config)

            assert result == 42.0
            mock_qb.get_latest_metric_value.assert_called_once()

    def test_get_latest_metric_fraction_operation(self):
        """Test fraction operation dispatch"""
        controller = DashboardController()

        with patch.object(controller, '_calculate_fraction', return_value=75.0) as mock_calc:
            column_config = {
                "operation": "fraction",
                "numerator": {},
                "denominator": {}
            }

            result = controller.get_latest_metric(client_id=1, column_config=column_config)

            assert result == 75.0
            mock_calc.assert_called_once_with(1, column_config)


class TestPrepareClientMetrics:
    """Test client metrics preparation"""

    def test_prepare_client_metrics(self):
        """Test metrics preparation for table display"""
        controller = DashboardController()

        with patch.object(controller, 'get_latest_metric') as mock_get:
            # Mock different values for different columns
            mock_get.side_effect = [65.0, 45.0, 50.0]  # CPU temp, VRM temp, GPU temp

            clients_data = [
                {"id": 1, "hostname": "test-host"}
            ]

            # Use minimal TABLE_COLUMNS
            from server.dashboard.controller import TABLE_COLUMNS
            with patch('server.dashboard.controller.TABLE_COLUMNS', [
                {"metric_name": "cpu_temp", "header": "CPU", "unit": "°", "css_class": "cpu"},
                {"metric_name": "vrm_temp", "header": "VRM", "unit": "°", "css_class": "vrm"},
                {"metric_name": "gpu_temp", "header": "GPU", "unit": "°", "css_class": "gpu"},
            ]):
                result = controller._prepare_client_metrics(clients_data)

            assert len(result) == 1
            assert "metric_values" in result[0]
            assert "cpu" in result[0]["metric_values"]
            assert result[0]["metric_values"]["cpu"]["value"] == 65.0
```

---

## Phase 5: Integration Tests - 2 hours

**Create**: `tests/integration/test_dashboard_routes.py`

```python
"""Integration tests for dashboard routes"""
import pytest
from fastapi.testclient import TestClient
from server.core.server import create_app


@pytest.fixture
def app_client(test_db):
    """Create test API client"""
    app = create_app()
    return TestClient(app)


class TestDashboardRoutes:
    """Test dashboard HTTP endpoints"""

    def test_dashboard_loads(self, app_client, sample_metrics):
        """Test that dashboard page loads"""
        response = app_client.get("/dashboard", auth=("admin", "test_token"))

        assert response.status_code == 200
        assert b"dcmon Dashboard" in response.content

    def test_dashboard_refresh_clients(self, app_client, sample_metrics):
        """Test HTMX client table refresh"""
        response = app_client.get("/dashboard/refresh/clients", auth=("admin", "test_token"))

        assert response.status_code == 200
        assert b"test-host" in response.content
```

---

## Implementation Schedule

| Phase | Task | Time | Status |
|-------|------|------|--------|
| 1 | Remove pandas from metric_queries.py | 2h | Pending |
| 1 | Update metrics_routes.py for new return types | 1h | Pending |
| 2 | Setup pytest infrastructure | 1h | Pending |
| 3 | Write MetricQueryBuilder unit tests | 2h | Pending |
| 4 | Write DashboardController unit tests | 2h | Pending |
| 5 | Write integration tests | 2h | Pending |
| **Total** | | **10h** | |

---

## Success Criteria

✅ **No pandas dependency**: All pandas code removed
✅ **Architecture preserved**: DashboardController and MetricQueryBuilder intact
✅ **80%+ test coverage**: Unit + integration tests
✅ **All tests passing**: Green build
✅ **Same functionality**: No regressions
✅ **Better maintainability**: Testable, documented code

---

## Next Steps

1. Start with Phase 1: Remove pandas
2. Run existing code to verify no regressions
3. Add tests incrementally (TDD approach)
4. Document any changes to API interfaces

