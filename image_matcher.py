"""
image_matcher.py

Modular image matching system for product comparison.
Supports multiple matching algorithms:
- ResNet50Matcher: Deep learning embeddings + geometric verification (high accuracy)
- PHashMatcher: Legacy pHash + SIFT matching (fallback)

Usage:
    from image_matcher import ResNet50Matcher
    
    matcher = ResNet50Matcher(use_sift=True, use_gpu=True)
    matches, missing = matcher.match_folders(db_folder, site_folder)
"""

import os
from pathlib import Path
from typing import List, Tuple, Dict, Optional
from abc import ABC, abstractmethod

import numpy as np
from PIL import Image
import cv2

# Optional deep learning imports
try:
    import torch
    import torch.nn as nn
    from torchvision import models, transforms
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    print("[WARN] PyTorch not available. ResNet50Matcher will not work.")

# Optional hash-based matching
try:
    import imagehash
    IMAGEHASH_AVAILABLE = True
except ImportError:
    IMAGEHASH_AVAILABLE = False
    print("[WARN] imagehash not available. PHashMatcher will not work.")

# Optional SSIM
try:
    from skimage.metrics import structural_similarity as sk_ssim
    SSIM_AVAILABLE = True
except ImportError:
    SSIM_AVAILABLE = False


# ===================== CONFIGURATION =====================

# Image file extensions
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif", ".gif", ".jfif", ".avif"}

# ResNet50 settings
EMBED_DIM = 2048
DEFAULT_TOP_K = 5
DEFAULT_SIM_THRESHOLD = 0.70
DEFAULT_MIN_INLIERS = 15  # Baseline for moderate similarity
DEFAULT_WHITE_THRESH = 240
DEFAULT_MIN_NONWHITE_RATIO = 0.01

# Adaptive inlier thresholds based on similarity
# For very high similarity (>0.95), we can be more lenient with inliers
# This handles cases where images are same but different sizes/resolutions
ADAPTIVE_INLIER_MAP = [
    (0.95, 8),   # Very high similarity: only need 8 inliers
    (0.90, 12),  # High similarity: only need 12 inliers  
    (0.80, 15),  # Good similarity: standard 15 inliers
    (0.70, 20),  # Lower similarity: need more proof (20 inliers)
]

# ORB/SIFT settings
DEFAULT_ORB_FEATURES = 2000
DEFAULT_SIFT_FEATURES = 2000
DEFAULT_RANSAC_THRESHOLD = 5.0
DEFAULT_LOWE_RATIO = 0.75


# ===================== BASE CLASS =====================

class BaseImageMatcher(ABC):
    """Abstract base class for image matchers."""
    
    @abstractmethod
    def match_folders(
        self,
        db_folder: str,
        site_folder: str
    ) -> Tuple[List[Tuple[str, str, float, int]], List[Tuple[str, Optional[str], float, int]]]:
        """
        Match images from database folder to website folder.
        
        Args:
            db_folder: Path to database images
            site_folder: Path to website images
            
        Returns:
            matches: List of (db_path, site_path, similarity, inliers)
            missing: List of (db_path, best_candidate_or_None, best_sim, best_inliers)
        """
        pass
    
    @staticmethod
    def is_image_file(path: Path) -> bool:
        """Check if file is an image."""
        return path.suffix.lower() in IMAGE_EXTS
    
    @staticmethod
    def list_images(folder: Path) -> List[Path]:
        """List all images in folder."""
        if not folder.is_dir():
            return []
        return sorted([p for p in folder.iterdir() if p.is_file() and BaseImageMatcher.is_image_file(p)])


# ===================== RESNET50 MATCHER =====================

class ResNet50Matcher(BaseImageMatcher):
    """
    High-accuracy matcher using ResNet50 deep learning embeddings + geometric verification.
    
    Pipeline:
    1. Compute ResNet50 embeddings for all images
    2. Find top-K candidates using cosine similarity
    3. Verify candidates with ORB/SIFT + RANSAC
    4. Apply smart white background cropping for product images
    """
    
    def __init__(
        self,
        top_k: int = DEFAULT_TOP_K,
        sim_threshold: float = DEFAULT_SIM_THRESHOLD,
        min_inliers: int = DEFAULT_MIN_INLIERS,
        use_sift: bool = True,
        use_gpu: bool = True,
        white_thresh: int = DEFAULT_WHITE_THRESH,
        one_to_one: bool = True,  # NEW: Prevent duplicate matches
        verbose: bool = True
    ):
        if not TORCH_AVAILABLE:
            raise ImportError("PyTorch is required for ResNet50Matcher. Install with: pip install torch torchvision")
        
        self.top_k = top_k
        self.sim_threshold = sim_threshold
        self.min_inliers = min_inliers
        self.use_sift = use_sift
        self.white_thresh = white_thresh
        self.one_to_one = one_to_one  # NEW
        self.verbose = verbose
        
        # Device selection
        if use_gpu and torch.cuda.is_available():
            self.device = torch.device("cuda")
            if verbose:
                print(f"[INFO] Using GPU: {torch.cuda.get_device_name(0)}")
        else:
            self.device = torch.device("cpu")
            if verbose:
                print("[INFO] Using CPU")
        
        # Build ResNet50 feature extractor
        if verbose:
            print("[INFO] Loading ResNet50 model...")
        self.model, self.preprocess = self._build_resnet50()
        if verbose:
            print("[INFO] ResNet50 ready!")
    
    def _build_resnet50(self):
        """Build ResNet50 feature extractor."""
        try:
            weights = models.ResNet50_Weights.DEFAULT
            resnet = models.resnet50(weights=weights)
        except Exception:
            resnet = models.resnet50(pretrained=True)
        
        # Remove FC layer, keep up to global pooling
        backbone = nn.Sequential(*list(resnet.children())[:-1]).to(self.device)
        backbone.eval()
        
        preprocess = transforms.Compose([
            transforms.Resize(256),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize(
                mean=[0.485, 0.456, 0.406],
                std=[0.229, 0.224, 0.225],
            ),
        ])
        
        return backbone, preprocess
    
    def _get_adaptive_min_inliers(self, similarity: float) -> int:
        """Get minimum inlier threshold based on similarity score.
        
        Higher similarity = lower inlier requirement (handles size differences)
        Lower similarity = higher inlier requirement (need more geometric proof)
        """
        for sim_thresh, inlier_req in ADAPTIVE_INLIER_MAP:
            if similarity >= sim_thresh:
                return inlier_req
        return self.min_inliers
    
    def _image_to_embedding(self, path: Path) -> np.ndarray:
        """Convert image to L2-normalized embedding."""
        img = Image.open(path).convert("RGB")
        x = self.preprocess(img).unsqueeze(0).to(self.device)
        with torch.no_grad():
            feat = self.model(x)  # [1, 2048, 1, 1]
        feat = feat.squeeze().cpu().numpy().astype("float32")  # [2048]
        norm = np.linalg.norm(feat) + 1e-8
        feat = feat / norm
        return feat
    
    def _compute_folder_embeddings(self, folder: Path) -> Tuple[np.ndarray, List[Path]]:
        """Compute embeddings for all images in folder."""
        paths = self.list_images(folder)
        if not paths:
            return np.zeros((0, EMBED_DIM), dtype="float32"), []
        
        embs = []
        kept_paths = []
        for p in paths:
            try:
                vec = self._image_to_embedding(p)
                embs.append(vec)
                kept_paths.append(p)
            except Exception as e:
                if self.verbose:
                    print(f"[WARN] Failed to embed {p.name}: {e}")
        
        if not embs:
            return np.zeros((0, EMBED_DIM), dtype="float32"), []
        
        embs_arr = np.stack(embs, axis=0)
        return embs_arr, kept_paths
    


    def _read_and_crop_white_border(self, path: Path) -> Optional[np.ndarray]:
        """Crop pure white borders from left/right/top/bottom sides."""
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            return None
        
        h, w = img.shape
        
        # Find left border: first column that is NOT pure white
        left = 0
        for col in range(w):
            if np.mean(img[:, col]) < 250:
                left = col
                break
        
        # Find right border: last column that is NOT pure white
        right = w - 1
        for col in range(w - 1, -1, -1):
            if np.mean(img[:, col]) < 250:
                right = col
                break
        
        # Find top border: first row that is NOT pure white
        top = 0
        for row in range(h):
            if np.mean(img[row, :]) < 250:
                top = row
                break
        
        # Find bottom border: last row that is NOT pure white
        bottom = h - 1
        for row in range(h - 1, -1, -1):
            if np.mean(img[row, :]) < 250:
                bottom = row
                break
        
        # Only crop if we found valid borders
        if right > left and bottom > top:
            cropped = img[top:bottom+1, left:right+1]
            # Make sure we didn't crop too much (at least 50% of original)
            if cropped.shape[0] >= h * 0.3 and cropped.shape[1] >= w * 0.3:
                return cropped
        
        return img
    # def _read_and_crop_white_border(self, path: Path) -> Optional[np.ndarray]:
    #     """Read image and crop white borders."""
    #     img = cv2.imread(str(path), cv2.IMREAD_COLOR)
    #     if img is None:
    #         return None
        
    #     gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    #     h, w = gray.shape[:2]
        
    #     # Detect non-white pixels
    #     mask_nonwhite = gray < self.white_thresh
    #     num_nonwhite = np.count_nonzero(mask_nonwhite)
    #     total = h * w
        
    #     if num_nonwhite / max(total, 1) < DEFAULT_MIN_NONWHITE_RATIO:
    #         # Almost all white, don't crop
    #         return gray
        
    #     ys, xs = np.where(mask_nonwhite)
    #     y_min, y_max = ys.min(), ys.max()
    #     x_min, x_max = xs.min(), xs.max()
        
    #     # Add padding
    #     pad = 5
    #     y_min = max(0, y_min - pad)
    #     y_max = min(h - 1, y_max + pad)
    #     x_min = max(0, x_min - pad)
    #     x_max = min(w - 1, x_max + pad)
        
    #     return gray[y_min:y_max+1, x_min:x_max+1]
    
    def _count_inlier_matches(self, img1_path: Path, img2_path: Path) -> int:
        """Count RANSAC inlier matches between two images."""
        gray1 = self._read_and_crop_white_border(img1_path)
        gray2 = self._read_and_crop_white_border(img2_path)
        
        if gray1 is None or gray2 is None:
            return 0
        
        # Try SIFT first, fallback to ORB
        local_use_sift = self.use_sift
        if local_use_sift:
            try:
                _ = cv2.SIFT_create()
            except AttributeError:
                if self.verbose:
                    print("[WARN] SIFT not available, using ORB")
                local_use_sift = False
        
        if local_use_sift:
            detector = cv2.SIFT_create(nfeatures=DEFAULT_SIFT_FEATURES)
            norm_type = cv2.NORM_L2
        else:
            detector = cv2.ORB_create(nfeatures=DEFAULT_ORB_FEATURES)
            norm_type = cv2.NORM_HAMMING
        
        kp1, des1 = detector.detectAndCompute(gray1, None)
        kp2, des2 = detector.detectAndCompute(gray2, None)
        
        if des1 is None or des2 is None or len(kp1) < 4 or len(kp2) < 4:
            return 0
        
        bf = cv2.BFMatcher(norm_type)
        matches = bf.knnMatch(des1, des2, k=2)
        
        good = []
        for pair in matches:
            if len(pair) < 2:
                continue
            m, n = pair
            if m.distance < DEFAULT_LOWE_RATIO * n.distance:
                good.append(m)
        
        if len(good) < 8:
            return len(good)
        
        src_pts = np.float32([kp1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        dst_pts = np.float32([kp2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
        
        H, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, DEFAULT_RANSAC_THRESHOLD)
        if H is None or mask is None:
            return 0
        
        inliers = int(mask.ravel().sum())
        return inliers
    
    def match_folders(
        self,
        db_folder: str,
        site_folder: str
    ) -> Tuple[List[Tuple[str, str, float, int]], List[Tuple[str, Optional[str], float, int]]]:
        """
        Match database images to website images.
        
        Returns:
            matches: [(db_path, site_path, similarity, inliers), ...]
            missing: [(db_path, best_candidate_or_None, best_sim, best_inliers), ...]
        """
        db_folder = Path(db_folder)
        site_folder = Path(site_folder)
        
        if self.verbose:
            print(f"[INFO] Database folder: {db_folder}")
            print(f"[INFO] Website folder: {site_folder}")
        
        # Compute website embeddings
        if self.verbose:
            print("[INFO] Computing website embeddings...")
        site_embs, site_paths = self._compute_folder_embeddings(site_folder)
        num_site = len(site_paths)
        
        if self.verbose:
            print(f"[INFO] Website images: {num_site}")
        
        if num_site == 0:
            if self.verbose:
                print("[WARN] No website images found")
            matches = []
            missing = []
            for db_path in self.list_images(db_folder):
                missing.append((str(db_path), None, 0.0, 0))
            return matches, missing
        
        # Process database images
        db_paths = self.list_images(db_folder)
        if self.verbose:
            print(f"[INFO] Database images: {len(db_paths)}")
        
        # NEW: Track used website images for one-to-one matching
        used_site_paths = set() if self.one_to_one else None
        
        # First pass: collect all potential matches with scores
        all_candidates = []  # List of (db_path, site_path, similarity, inliers, adaptive_min_inliers)
        
        for idx, db_path in enumerate(db_paths, start=1):
            if self.verbose:
                print(f"\n[{idx}/{len(db_paths)}] {db_path.name}")
            
            try:
                db_emb = self._image_to_embedding(db_path)
            except Exception as e:
                if self.verbose:
                    print(f"[WARN] Could not embed: {e}")
                all_candidates.append((db_path, None, 0.0, 0, self.min_inliers))
                continue
            
            # Cosine similarities
            sims = site_embs @ db_emb
            k = min(self.top_k, num_site)
            top_idx = np.argsort(-sims)[:k]
            
            best_site = None
            best_sim = -1.0
            best_inliers = -1
            best_adaptive_min = self.min_inliers
            best_passes_threshold = False  # Track if best candidate passes its threshold
            
            for rank, j in enumerate(top_idx, start=1):
                site_path = site_paths[j]
                sim = float(sims[j])
                # mmmmm
                if self.verbose:
                    print(f"   Candidate #{rank}: {site_path.name}, sim={sim:.3f}")

                # mmmm
                
                
                # if sim < self.sim_threshold:
                #     if self.verbose:
                #         print("      -> Below threshold, skipping")
                #     continue
                
                # inliers = self._count_inlier_matches(db_path, site_path)
                
                if sim < self.sim_threshold:
                    if self.verbose:
                        print("      -> Below threshold, skipping")
                    continue

                # NEW: If similarity is very high (>0.96), trust it without geometric verification
                if sim >= 0.94:
                    inliers = 999  # Fake high inliers to force match
                    if self.verbose:
                        print(f"      -> Very high similarity ({sim:.3f}), trusting embedding directly")
                else:
                    inliers = self._count_inlier_matches(db_path, site_path)



                adaptive_min = self._get_adaptive_min_inliers(sim)  # Dynamic threshold based on similarity
                passes_threshold = (inliers >= adaptive_min)
                
                if self.verbose:
                    print(f"      -> inliers={inliers} (adaptive_min={adaptive_min})")
                
                # Track best - FIXED: Prioritize candidates that pass their adaptive threshold
                # This ensures high-similarity candidates with sufficient inliers are preferred
                # over low-similarity candidates with more inliers that fail their threshold
                should_update = False
                
                if best_site is None:
                    # First valid candidate
                    should_update = True
                elif passes_threshold and not best_passes_threshold:
                    # This passes its threshold, best doesn't -> always better
                    should_update = True
                elif passes_threshold and best_passes_threshold:
                    # Both pass -> prefer more inliers, then higher similarity (original logic)
                    if (inliers > best_inliers) or (inliers == best_inliers and sim > best_sim):
                        should_update = True
                elif not passes_threshold and not best_passes_threshold:
                    # Both fail -> prefer more inliers, then higher similarity (original logic)
                    if (inliers > best_inliers) or (inliers == best_inliers and sim > best_sim):
                        should_update = True
                # If this fails but best passes -> don't update (should_update stays False)
                
                if should_update:
                    best_inliers = inliers
                    best_sim = sim
                    best_site = site_path
                    best_adaptive_min = adaptive_min
                    best_passes_threshold = passes_threshold
            
            all_candidates.append((db_path, best_site, best_sim, best_inliers, best_adaptive_min))
        
        # Second pass: resolve conflicts and create final matches
        if self.one_to_one:
            # Sort by quality: prioritize higher similarity and more inliers
            all_candidates.sort(key=lambda x: (-x[2], -x[3]))  # Sort by sim desc, then inliers desc
        
        matches = []
        missing = []
        
        for db_path, best_site, best_sim, best_inliers, adaptive_min in all_candidates:
            # Check if this is a valid match
            if best_site is None:
                missing.append((str(db_path), None, 0.0, 0))
                continue
                
            # NEW: Skip if site image already used (one-to-one constraint)
            if self.one_to_one and best_site in used_site_paths:
                if self.verbose:
                    print(f"   [CONFLICT] {db_path.name} -> {best_site.name} already matched, skipping")
                missing.append((str(db_path), str(best_site), best_sim, best_inliers))
                continue
            
            # Check against adaptive threshold instead of fixed threshold
            if best_sim >= self.sim_threshold and best_inliers >= adaptive_min:
                if self.verbose:
                    print(f"   [MATCH] {db_path.name} -> {best_site.name} (sim={best_sim:.3f}, inliers={best_inliers}, min_required={adaptive_min})")
                matches.append((str(db_path), str(best_site), best_sim, best_inliers))
                if self.one_to_one:
                    used_site_paths.add(best_site)
            else:
                if self.verbose:
                    print(f"   [MISSING] No match (best_sim={best_sim:.3f}, best_inliers={best_inliers}, min_required={adaptive_min})")
                missing.append((str(db_path), str(best_site), best_sim, best_inliers))
        
        return matches, missing


# ===================== LEGACY PHASH MATCHER =====================

class PHashMatcher(BaseImageMatcher):
    """
    Legacy matcher using pHash + SIFT + SSIM + color histogram.
    Fallback when PyTorch is not available.
    """
    
    def __init__(
        self,
        top_k: int = 12,
        phash_strong: int = 60,
        phash_border: int = 90,
        sift_inliers_min: int = 15,
        sift_override: int = 120,
        ssim_min: float = 0.62,
        ssim_override: float = 0.80,
        hist_min: float = 0.90,
        hist_override: float = 0.96,
        verbose: bool = True
    ):
        if not IMAGEHASH_AVAILABLE:
            raise ImportError("imagehash required for PHashMatcher. Install with: pip install imagehash")
        
        self.top_k = top_k
        self.phash_strong = phash_strong
        self.phash_border = phash_border
        self.sift_inliers_min = sift_inliers_min
        self.sift_override = sift_override
        self.ssim_min = ssim_min
        self.ssim_override = ssim_override
        self.hist_min = hist_min
        self.hist_override = hist_override
        self.verbose = verbose
    
    def _phash(self, path: Path) -> Optional[int]:
        """Compute perceptual hash."""
        try:
            with Image.open(path) as im:
                h = imagehash.phash(im.convert("RGB"), hash_size=16)
                return int(str(h), 16)
        except Exception:
            return None
    
    def _phash_dist(self, h1: Optional[int], h2: Optional[int]) -> int:
        """Hamming distance between hashes."""
        if h1 is None or h2 is None:
            return 999999
        x = h1 ^ h2
        return bin(x).count("1")
    
    def _sift_inliers(self, a_path: Path, b_path: Path) -> int:
        """Count SIFT RANSAC inliers."""
        try:
            img1 = cv2.imread(str(a_path))
            img2 = cv2.imread(str(b_path))
            if img1 is None or img2 is None:
                return 0
            
            sift = cv2.SIFT_create(nfeatures=2000)
            k1, d1 = sift.detectAndCompute(img1, None)
            k2, d2 = sift.detectAndCompute(img2, None)
            
            if d1 is None or d2 is None or len(k1) < 8 or len(k2) < 8:
                return 0
            
            flann = cv2.FlannBasedMatcher(dict(algorithm=1, trees=5), dict(checks=64))
            knn = flann.knnMatch(d1, d2, k=2)
            
            good = []
            for pair in knn:
                if len(pair) < 2:
                    continue
                m, n = pair
                if m.distance < 0.75 * n.distance:
                    good.append(m)
            
            if len(good) < 8:
                return 0
            
            src = np.float32([k1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
            dst = np.float32([k2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
            H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
            
            return int(mask.sum()) if mask is not None else 0
        except Exception:
            return 0
    
    def _ssim(self, a_path: Path, b_path: Path) -> Optional[float]:
        """Compute SSIM."""
        if not SSIM_AVAILABLE:
            return None
        try:
            A = np.array(Image.open(a_path).convert("L"))
            B = np.array(Image.open(b_path).convert("L"))
            h = min(A.shape[0], B.shape[0])
            w = min(A.shape[1], B.shape[1])
            if h < 40 or w < 40:
                return None
            A, B = A[:h, :w], B[:h, :w]
            v, _ = sk_ssim(A, B, full=True)
            return float(v)
        except Exception:
            return None
    
    def _hist_corr(self, a_path: Path, b_path: Path) -> float:
        """Compute color histogram correlation."""
        try:
            a = np.array(Image.open(a_path).convert("RGB"))[:, :, ::-1]
            b = np.array(Image.open(b_path).convert("RGB"))[:, :, ::-1]
            
            def hist3(img):
                chans = cv2.split(img)
                out = []
                for ch in chans:
                    h = cv2.calcHist([ch], [0], None, [64], [0, 256])
                    cv2.normalize(h, h)
                    out.append(h)
                return out
            
            ha, hb = hist3(a), hist3(b)
            return float(sum(cv2.compareHist(ca, cb, cv2.HISTCMP_CORREL) for ca, cb in zip(ha, hb)) / 3.0)
        except Exception:
            return 0.0
    
    def _accept(self, phash_d: int, inl: int, ssim_v: Optional[float], hist: float) -> bool:
        """Decision logic."""
        if phash_d <= self.phash_strong:
            return True
        if phash_d <= self.phash_border:
            if inl >= self.sift_inliers_min:
                return True
            ok_ssim = (ssim_v is not None and ssim_v >= self.ssim_min)
            ok_hist = (hist >= self.hist_min)
            if ok_ssim and ok_hist:
                return True
            if ssim_v is not None and ssim_v >= self.ssim_min + 0.15:
                return True
            if hist >= self.hist_min + 0.07:
                return True
        if inl >= self.sift_override:
            return True
        if (ssim_v is not None and ssim_v >= self.ssim_override) and (hist >= self.hist_override):
            return True
        return False
    
    def match_folders(
        self,
        db_folder: str,
        site_folder: str
    ) -> Tuple[List[Tuple[str, str, float, int]], List[Tuple[str, Optional[str], float, int]]]:
        """Match using pHash + SIFT + SSIM + histogram."""
        db_folder = Path(db_folder)
        site_folder = Path(site_folder)
        
        db_imgs = self.list_images(db_folder)
        site_imgs = self.list_images(site_folder)
        
        if not db_imgs or not site_imgs:
            return [], [(str(p), None, 0.0, 0) for p in db_imgs]
        
        # pHash caches
        ph_site = {sp: self._phash(sp) for sp in site_imgs}
        ph_db = {dp: self._phash(dp) for dp in db_imgs}
        
        def shortlist(q: Path) -> List[Path]:
            qh = ph_db.get(q)
            scored = [(self._phash_dist(qh, ph_site.get(sp)), sp) for sp in site_imgs]
            scored.sort(key=lambda t: t[0])
            return [sp for _, sp in scored[:self.top_k]]
        
        matches = []
        missing = []
        used_site = set()
        
        for q in db_imgs:
            cands = shortlist(q)
            qh = ph_db.get(q)
            found = None
            
            for cand in cands:
                if cand in used_site:
                    continue
                
                d = self._phash_dist(qh, ph_site.get(cand))
                inl = self._sift_inliers(q, cand)
                ssv = self._ssim(q, cand)
                hc = self._hist_corr(q, cand)
                
                if self._accept(d, inl, ssv, hc):
                    found = cand
                    break
            
            if found is not None:
                matches.append((str(q), str(found), 0.0, 0))  # No sim/inliers in legacy
                used_site.add(found)
            else:
                missing.append((str(q), None, 0.0, 0))
        
        return matches, missing


# ===================== FACTORY =====================

def create_matcher(algorithm: str = "resnet50", **kwargs) -> BaseImageMatcher:
    """
    Factory function to create image matchers.
    
    Args:
        algorithm: "resnet50" or "phash_legacy"
        **kwargs: Algorithm-specific parameters
        
    Returns:
        BaseImageMatcher instance
    """
    if algorithm == "resnet50":
        return ResNet50Matcher(**kwargs)
    elif algorithm == "phash_legacy":
        return PHashMatcher(**kwargs)
    else:
        raise ValueError(f"Unknown algorithm: {algorithm}. Choose 'resnet50' or 'phash_legacy'")
