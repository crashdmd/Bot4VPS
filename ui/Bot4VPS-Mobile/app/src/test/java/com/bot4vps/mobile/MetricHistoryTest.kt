package com.bot4vps.mobile

import com.bot4vps.mobile.data.model.*
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class MetricHistoryTest {
    private fun history(text: String) = decodeMetricHistory(Json.parseToJsonElement(text).jsonObject, HistoryWindow(1, 1000))

    @Test fun readoutDoesNotMixSamplesWithDifferentTimestamps() {
        val data = history("""{"series":{"load1":[[100,1],[200,2]],"ram_pct":[[100,40],[250,80]]},"disks":[{"mount":"/","points":[[200,60]]}]}""")
        assertEquals(200L, data.nearestTime(195, data.window))
        assertEquals(2.0, data.value(data.series[0], 200)!!, 0.0)
        assertNull(data.value(data.series[1], 200))
        assertEquals(60.0, data.value(data.series[2], 200)!!, 0.0)
    }
    @Test fun missingIntervalsDoNotShowNeighbouringValues() {
        val data = history("""{"series":{"load1":[[100,1],[200,2]],"ram_pct":[[100,40],[200,80]]},"gaps":[{"from":100,"to":200}]}""")
        assertEquals(150L, data.nearestTime(150, data.window))
        assertNull(data.value(data.series[0], 150))
        assertEquals(1.0, data.value(data.series[0], 100)!!, 0.0)
    }
    @Test fun diskGapsDoNotHideValidMemorySamples() {
        val data = history("""{"series":{"ram_pct":[[150,40]],"disk_max_pct":[[150,70]]},"disk_gaps":[[100,200,"no_df"]]}""")
        assertEquals(40.0, data.value(data.series[1], 150)!!, 0.0)
        assertNull(data.value(data.series[2], 150))
    }
    @Test fun hourlyDataKeepsRawLoadAndNamesTheWorstDisk() {
        val data = history("""{"step":"hour","from":100,"to":300,"series":{"load1":[[100,0.5]],"disk_max_pct":[[100,78]]},"labels":{"disk_max_pct":[[100,"/var"]]}}""")
        assertTrue(data.hourly)
        assertFalse(data.series[0].percent)
        assertEquals("/var", data.diskLabels[100L])
        assertTrue(data.rawValues.isEmpty())
    }
    @Test fun zoomKeepsAnchorAndPanPreservesWindowLength() {
        val window = HistoryWindow(1000, 2000)
        assertEquals(HistoryWindow(1250, 1750), window.transform(zoom = 2f, now = 10000))
        assertEquals(HistoryWindow(1000, 1500), window.transform(zoom = 2f, anchor = 0f, now = 10000))
        assertEquals(HistoryWindow(750, 1750), window.transform(panFraction = .25f, now = 10000))
    }
    @Test fun gesturesCannotMoveIntoTheFutureOrCreateAnInvalidWindow() {
        val window = HistoryWindow(1000, 2000)
        assertEquals(HistoryWindow(1500, 2500), window.transform(panFraction = -100f, now = 2500))
        assertEquals(HistoryWindow(0, 1000), window.transform(panFraction = 100f, now = 2500))
        assertEquals(60L, window.transform(zoom = 100000f, now = 2500).span)
        assertEquals(window, window.transform(zoom = Float.NaN, now = 2500))
    }
}
