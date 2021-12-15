# (c) 2015-2022 Acellera Ltd http://www.acellera.com
# All Rights Reserved
# Distributed under HTMD Software License Agreement
# No redistribution in whole or part
#
from jobqueues.localqueue import LocalCPUQueue, LocalGPUQueue
import logging


logger = logging.getLogger(__name__)

logger.warning(
    "Please do not import from htmd.queues.localqueue. This will be deprecated. "
    "Use jobqueues.localqueue instead."
)
