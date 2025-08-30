#!/usr/bin/env python3
"""
Test script to measure the size of data sent by dcmon client
"""

import asyncio
import json
import sys
import os
import time
from dataclasses import asdict

sys.path.append(os.path.dirname(__file__))
from exporters import OSMetricsExporter, AptExporter, NvsmiExporter


def get_machine_id():
    """Mock machine ID"""
    return "test-machine-12345678"

async def measure_payload_size():
    """Measure the size of a typical payload"""
    print("Measuring dcmon client payload size...")
    print("=" * 50)
    
    # Collect all metrics like the real client
    collectors = [
        OSMetricsExporter(),
        AptExporter(),
        NvsmiExporter(),
    ]
    
    all_metrics = []
    for collector in collectors:
        metrics = await collector.safe_collect()
        all_metrics.extend(metrics)
    
    print(f"Collected {len(all_metrics)} total metrics")
    
    # Create the payload exactly like the real client
    metrics_data = []
    for metric in all_metrics:
        metric_dict = asdict(metric)
        metrics_data.append(metric_dict)
    
    payload = {
        "machine_id": get_machine_id(),
        "timestamp": int(time.time()),
        "metrics": metrics_data
    }
    
    # Convert to JSON (what gets sent over network)
    json_payload = json.dumps(payload)

    # Save to file
    with open("client_single_metrics.json", "w", encoding="utf-8") as f:
        f.write(json_payload)

    print("Saved to client_single_metrics.json")
    # Calculate sizes
    json_size = len(json_payload.encode('utf-8'))
    json_size_kb = json_size / 1024
    
    # Compressed size (gzip - what HTTP usually uses)
    import gzip
    compressed = gzip.compress(json_payload.encode('utf-8'))
    compressed_size = len(compressed)
    compressed_kb = compressed_size / 1024
    
    print(f"\nPayload Analysis:")
    print(f"  Metrics count: {len(all_metrics)}")
    print(f"  JSON size: {json_size:,} bytes ({json_size_kb:.1f} KB)")
    print(f"  Compressed: {compressed_size:,} bytes ({compressed_kb:.1f} KB)")
    print(f"  Compression ratio: {compressed_size/json_size*100:.1f}%")
    
    # Calculate daily/monthly data usage
    intervals_per_day = 24 * 60 * 60 / 30  # 30-second intervals
    daily_uncompressed = json_size * intervals_per_day / (1024*1024)  # MB
    daily_compressed = compressed_size * intervals_per_day / (1024*1024)  # MB
    
    print(f"\nData Usage (per client):")
    print(f"  Per transmission: {json_size_kb:.1f} KB uncompressed, {compressed_kb:.1f} KB compressed")
    print(f"  Daily: {daily_uncompressed:.1f} MB uncompressed, {daily_compressed:.1f} MB compressed")
    print(f"  Monthly: {daily_uncompressed*30:.0f} MB uncompressed, {daily_compressed*30:.0f} MB compressed")
    
    # Calculate for 100 clients
    print(f"\nTotal Usage (100 clients):")
    print(f"  Daily: {daily_compressed*100:.0f} MB compressed")
    print(f"  Monthly: {daily_compressed*100*30/1024:.1f} GB compressed")
    
    # Show sample metrics breakdown
    print(f"\nSample Metrics (first 5):")
    for i, metric in enumerate(all_metrics[:5]):
        metric_json = json.dumps(asdict(metric))
        print(f"  {i+1}. {metric.name}: {len(metric_json)} bytes")
    
    # Show biggest metrics
    metric_sizes = [(asdict(m), len(json.dumps(asdict(m)))) for m in all_metrics]
    metric_sizes.sort(key=lambda x: x[1], reverse=True)
    
    print(f"\nLargest Metrics:")
    for i, (metric_dict, size) in enumerate(metric_sizes[:3]):
        print(f"  {i+1}. {metric_dict['name']}: {size} bytes")
    
    return json_size, compressed_size, len(all_metrics)

if __name__ == "__main__":
    asyncio.run(measure_payload_size())