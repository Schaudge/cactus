#include "CuTest.h"
#include "sonLib.h"
#include "matchingAlgorithms.h"

static int32_t nodeNumber = 0;
static stSortedSet *edges = NULL;
static stList *edgesList = NULL;

static void teardown() {
    //Gets rid of the random flower.
    if(edges != NULL) {
        stSortedSet_destruct(edges);
        assert(edgesList != NULL);
        stList_destruct(edgesList);
        edgesList = NULL;
        edges = NULL;
        nodeNumber = 0;
    }
}

static void setup() {
    teardown();
    do {
        nodeNumber = st_randomInt(0, 100);
    } while(nodeNumber % 2 != 0);
    if(nodeNumber > 0) {
        int32_t edgeNumber = st_randomInt(0, nodeNumber * 10);
        edges = stSortedSet_construct3((int (*)(const void *, const void *))stIntTuple_cmpFn, (void (*)(void *))stIntTuple_destruct);
        stSortedSet *seen = stSortedSet_construct3((int (*)(const void *, const void *))stIntTuple_cmpFn, (void (*)(void *))stIntTuple_destruct);
        for(int32_t i=0; i<edgeNumber; i++) {
            int32_t from = st_randomInt(0, nodeNumber);
            int32_t to = st_randomInt(0, nodeNumber);
            if(from != to) {
                stIntTuple *edge1 = stIntTuple_construct(2, from, to);
                if(stSortedSet_search(seen, edge1) == NULL) {
                    stSortedSet_insert(seen, edge1);
                    stSortedSet_insert(seen, stIntTuple_construct(2, to, from));
                    stSortedSet_insert(edges, stIntTuple_construct(3, from, to, st_randomInt(0, 100)));
                }
                else {
                    stIntTuple_destruct(edge1);
                }
            }
        }
        stSortedSet_destruct(seen);
        edgesList = stSortedSet_getList(edges);
    }
}


static void checkMatching(CuTest *testCase, stList *matching, bool perfectMatching) {
    /*
     * Checks the matching is valid.
     */
    stSortedSet *seen = stSortedSet_construct3((int (*)(const void *, const void *))stIntTuple_cmpFn, (void (*)(void *))stIntTuple_destruct);
    for(int32_t i=0; i<stList_length(matching); i++) {
        stIntTuple *edge = stList_get(matching, i);
        int32_t from = stIntTuple_getPosition(edge, 0);
        int32_t to = stIntTuple_getPosition(edge, 1);
        int32_t weight = stIntTuple_getPosition(edge, 2);

        /*
         * Check bounds are valid.
         */
        CuAssertTrue(testCase, from != to);
        CuAssertTrue(testCase, from >= 0 && from < nodeNumber);
        CuAssertTrue(testCase, to >= 0 && to < nodeNumber);
        CuAssertTrue(testCase, weight >= 0 && weight < 100);

        /*
         * Check the matching is valid.
         */
        stIntTuple *fromTuple = stIntTuple_construct(1, from);
        CuAssertTrue(testCase, stSortedSet_search(seen, fromTuple) == NULL);
        stSortedSet_insert(seen, fromTuple);
        stIntTuple *toTuple = stIntTuple_construct(1, to);
        CuAssertTrue(testCase, stSortedSet_search(seen, toTuple) == NULL);
        stSortedSet_insert(seen, toTuple);

        /*
         * Check that any edge with non-zero weight is in our original set.
         */
        if(weight > 0.0) {
            CuAssertTrue(testCase, stSortedSet_search(edges, edge) != NULL);
        }
    }
    if(perfectMatching) {
        CuAssertTrue(testCase, stList_length(matching)*2 == nodeNumber);
        CuAssertTrue(testCase, stSortedSet_size(seen) == nodeNumber);
    }
    stSortedSet_destruct(seen);
}

static int32_t matchingWeight(stList *matching) {
    int32_t totalWeight = 0;
    for(int32_t i=0; i<stList_length(matching); i++) {
        stIntTuple *edge = stList_get(matching, i);
        totalWeight += stIntTuple_getPosition(edge, 2);
    }
    return totalWeight;
}

static void testGreedy(CuTest *testCase) {
    for(int32_t i=0; i<100; i++) {
        setup();
        stList *matching = chooseMatching_greedy(edgesList, nodeNumber);
        checkMatching(testCase, matching, 0);
        int32_t totalWeight = matchingWeight(matching);
        st_uglyf("The total weight of the greedy matching is %i\n", totalWeight);
        stList_destruct(matching);
        teardown();
    }
}

static void testMaximumWeight(CuTest *testCase) {
    /*
     * Creates random graphs, constructs matchings with the blossom5 and maximumWeight algorithms
     * and checks that they have equal weight and higher or equal weight to the greedy matching
     * as well as sanity checking the matchings (the blossom matching is perfect).
     */
    for(int32_t i=0; i<100; i++) {
        setup();
        stList *greedyMatching = chooseMatching_greedy(edgesList, nodeNumber);
        stList *blossomMatching = chooseMatching_blossom5(edgesList, nodeNumber);
        stList *maximumWeightMatching = chooseMatching_maximumWeightMatching(edgesList, nodeNumber);
        checkMatching(testCase, greedyMatching, 0);
        checkMatching(testCase, blossomMatching, 0);
        checkMatching(testCase, maximumWeightMatching, 0);
        int32_t totalGreedyWeight = matchingWeight(greedyMatching);
        int32_t totalBlossumWeight = matchingWeight(blossomMatching);
        int32_t totalMaximumWeightWeight = matchingWeight(maximumWeightMatching);
        st_uglyf("The total weight of the greedy matching is %i, the total weight of the blossom5 matching is %i, the total weight of the maximum weight matching is %i\n",
                totalGreedyWeight, totalBlossumWeight, totalMaximumWeightWeight);
        st_uglyf("The total cardinality of the greedy matching is %i, the total cardinality of the blossom5  matching is %i, the total cardinality of the maximum weight matching is %i\n",
                        stList_length(greedyMatching), stList_length(blossomMatching), stList_length(maximumWeightMatching));
        CuAssertTrue(testCase, totalGreedyWeight <= totalBlossumWeight);
        CuAssertTrue(testCase, totalGreedyWeight <= totalMaximumWeightWeight);
        CuAssertTrue(testCase, totalBlossumWeight == totalMaximumWeightWeight);
        //CuAssertTrue(testCase, stList_length(greedyMatching) <= stList_length(blossomMatching));
        stList_destruct(greedyMatching);
        stList_destruct(blossomMatching);
        stList_destruct(maximumWeightMatching);
        teardown();
    }
}

static void testMaximumCardinality(CuTest *testCase) {
    /*
     * Tests a maximum (cardinality) matching algorithm, checking that it has higher or equal
     * cardinality to the greedy algorithm.
     */
    for(int32_t i=0; i<100; i++) {
        setup();
        stList *greedyMatching = chooseMatching_greedy(edgesList, nodeNumber);
        stList *edmondsMatching = chooseMatching_maximumCardinalityMatching(edgesList, nodeNumber);
        checkMatching(testCase, greedyMatching, 0);
        checkMatching(testCase, edmondsMatching, 0);

        int32_t totalGreedyWeight = matchingWeight(greedyMatching);
        int32_t totalEdmondsWeight = matchingWeight(edmondsMatching);
        st_uglyf("The total weight of the greedy matching is %i, the total weight of the edmonds matching is %i\n",
                totalGreedyWeight, totalEdmondsWeight);
        st_uglyf("The total cardinality of the greedy matching is %i, the total cardinality of the edmonds matching is %i\n",
                stList_length(greedyMatching), stList_length(edmondsMatching));
        CuAssertTrue(testCase, stList_length(greedyMatching) <= stList_length(edmondsMatching));
        stList_destruct(greedyMatching);
        stList_destruct(edmondsMatching);
        teardown();
    }
}

CuSuite* matchingAlgorithmsTestSuite(void) {
    CuSuite* suite = CuSuiteNew();
    SUITE_ADD_TEST(suite, testGreedy);
    SUITE_ADD_TEST(suite, testMaximumWeight);
    SUITE_ADD_TEST(suite, testMaximumCardinality);

    return suite;
}
