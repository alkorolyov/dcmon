#!/usr/bin/env python3
"""
Test script for dcmon client functionality
"""

import asyncio
import logging
import sys
import os

sys.path.append(os.path.dirname(__file__))

from client.exporters import OSMetricsExporter, IpmiExporter, AptExporter, NvmeExporter, NvsmiExporter


async def test_os_metrics():
    """Test OS metrics collection"""
    print("Testing OS Metrics Collection...")
    
    collector = OSMetricsExporter(logger=logging.getLogger(__name__))
    metrics = await collector.collect()
    
    print(f"Collected {len(metrics)} OS metrics:")
    for metric in metrics:  # Show all metrics
        labels_str = ""
        if metric.labels:
            labels_items = [f'{k}="{v}"' for k, v in metric.labels.items()]
            labels_str = "{" + ",".join(labels_items) + "}"
        print(f"  {metric.name}{labels_str} = {metric.value}")
    
    return metrics

async def test_script_exporters():
    """Test script-based exporters"""
    exporters = [
        ("IPMI", IpmiExporter()),
        ("APT", AptExporter()),
        ("NVMe", NvmeExporter()),
        ("NVSMI", NvsmiExporter()),
    ]
    
    for name, exporter in exporters:
        print(f"\nTesting {name} Exporter...")
        try:
            metrics = await exporter.collect()
            print(f"  Collected {len(metrics)} metrics")
            
            # Show all metrics
            for metric in metrics:
                labels_str = ""
                if metric.labels:
                    labels_items = [f'{k}="{v}"' for k, v in metric.labels.items()]
                    labels_str = "{" + ",".join(labels_items) + "}"
                print(f"    {metric.name}{labels_str} = {metric.value}")
                
        except Exception as e:
            print(f"  Error: {e}")

async def main():
    """Main test function"""
    print("dcmon Client Test Suite")
    print("=" * 50)
    
    # Test OS metrics
    try:
        os_metrics = await test_os_metrics()
        print(f"\n✅ OS metrics test passed ({len(os_metrics)} metrics)")
    except Exception as e:
        print(f"\n❌ OS metrics test failed: {e}")
    
    # Test script exporters
    try:
        await test_script_exporters()
        print(f"\n✅ Script exporters test completed")
    except Exception as e:
        print(f"\n❌ Script exporters test failed: {e}")

if __name__ == "__main__":
    asyncio.run(main())