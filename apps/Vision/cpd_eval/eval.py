import cv2
import numpy as np
import matplotlib.pyplot as plt
from cpd_isp import DxfGenerator
from scipy.spatial import cKDTree

class Evaluator:
    def __init__(self, contour: np.array, reference: np.array, mm_per_pixel: float):

        self.mm_per_pixel = mm_per_pixel

        self.contour_raw = contour.reshape(-1, 2) * self.mm_per_pixel
        self.reference_raw = reference

        # Find centroid and angle of primary axis of contours
        contour_center, contour_angle = self._moments(self.contour_raw)
        ref_center, ref_angle = self._moments(self.reference_raw)

        # Rotate and shift to overlap
        self.contour = self._rotate(self.contour_raw, contour_center, contour_angle)
        self.reference = self._rotate(self.reference_raw, ref_center, ref_angle)

        self.reference_den = self._densify(self.reference)

    
    def _moments(self, contour: np.array):
        M = cv2.moments(contour.astype(np.float32))
        cx = M['m10'] / M['m00']
        cy = M['m01'] / M['m00']
        angle = 0.5 * np.arctan2(2*M['mu11'], M['mu20'] - M['mu02'])

        return np.array([cx, cy]), -angle 
    

    def _rotate(self, contour, center, theta):
        R = np.array([
            [np.cos(theta), -np.sin(theta)],
            [np.sin(theta),  np.cos(theta)]
        ])

        return (contour - center) @ R.T
    

    def _densify(self, poly, n=10):
        pts = []
        for i in range(len(poly)-1):
            p1, p2 = poly[i], poly[i+1]
            for t in np.linspace(0, 1, n):
                pts.append(p1*(1-t) + p2*t)
        return np.array(pts)
    

    def _closest_distances(self, scan, reference):
        tree = cKDTree(reference)
        dists, _ = tree.query(scan)  # nearest neighbor for each scan point
        return dists
    

    def point_to_segment(self, p, a, b):
        ab = b - a
        ap = p - a

        ab_len2 = np.dot(ab, ab)
        t = np.dot(ap, ab) / np.dot(ab, ab)
        t = np.clip(t, 0, 1)

        closest = a + t * ab
        dist = np.linalg.norm(p - closest)

        edge_length = np.sqrt(ab_len2)
        dist_to_a = t * edge_length
        dist_to_b = (1 - t) * edge_length

        return dist, t, closest, dist_to_a, dist_to_b
    

    def mean_error_sym(self):
        d1 = self._closest_distances(self.contour, self.reference)
        d2 = self._closest_distances(self.reference, self.contour)

        return (np.mean(d1) + np.mean(d2)) / 2


    def hausdorff_error(self):
        d1 = self._closest_distances(self.contour, self.reference)
        d2 = self._closest_distances(self.reference, self.contour)

        return max(np.max(d1), np.max(d2))
    

    def per_edge_deviation(self):
        edges = [(self.reference[i], self.reference[i+1]) for i in range(len(self.reference)-1)]

        all_dists = []
        all_edge_ids = []
        all_t = []

        for p in self.contour:
            best_dist = np.inf
            best_edge = -1
            best_t = None

            for i, (a, b) in enumerate(edges):
                d, t, _, da, db= self.point_to_segment(p, a, b)

                corner_tol = 1.0  # mm 

                if da < corner_tol or db < corner_tol:
                    continue  # ignore this edge for this point

                if d < best_dist:
                    best_dist = d
                    best_edge = i
                    best_t = t

            all_dists.append(best_dist)
            all_edge_ids.append(best_edge)
            all_t.append(best_t)

        return np.mean(np.array(all_dists)), np.array(all_edge_ids), np.array(all_t)
    

    def plot_per_edge_deviation(self):
        _, ids, _ = self.per_edge_deviation()

        plt.plot(self.reference_den[:, 0], self.reference_den[:, 1], label="Reference")

        for i in range(len(self.reference)-1):
            filtered_points = self.contour[ids == i]
            plt.scatter(filtered_points[:, 0], filtered_points[:, 1], s=5, label=f"Edge {i}")

        plt.gca().set_aspect('equal', adjustable='box')
        plt.legend(loc='center left', bbox_to_anchor=(1, 0.5))
        plt.tight_layout()
        plt.show()

    def plot(self, contour1, contour2):
        # contour1, contour2: shape (N, 2)
        plt.scatter(contour1[:, 0], contour1[:, 1], s=5, label="contour1")
        plt.scatter(contour2[:, 0], contour2[:, 1], s=5, label="contour2")

        plt.gca().set_aspect('equal', adjustable='box')
        plt.legend()
        plt.show()


if __name__ == "__main__":
    img = cv2.imread("tests/output_images/test20.png")

    dxf = DxfGenerator(img, 150, 150)

    dxf.get_contours(2000)


    eval = Evaluator(
        dxf.big_contours[0],
        np.array([
            [0.0, 0.0],
            [70.0, 0.0],
            [70.0, 25.0],
            [50.0, 25.0],
            [50.0, 5.0],
            [45.0, 5.0],
            [45.0, 25.0],
            [0.0, 25.0],
            [0.0, 0.0]
        ]),
        0.05
    )

    eval.plot_per_edge_deviation()

    #eval.plot(eval.contour, eval.reference)




